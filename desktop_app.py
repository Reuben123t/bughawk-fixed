"""BugHawk native Windows desktop client.

The client keeps analysis results locally under %LOCALAPPDATA%\\BugHawk and
does not load dotenv files. API credentials must already be present in the
process environment when the app is launched.
"""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import tkinter as tk
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from urllib.parse import urlparse

import httpx


APP_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "BugHawk"
HISTORY_FILE = APP_DIR / "history.json"
ALLOWED_EXTENSIONS = {".py", ".toml", ".ini", ".cfg", ".txt"}
BLOCKED_FILENAMES = {".env", ".env.example"}


@dataclass
class RunResult:
    status: str
    exit_code: int | None
    stdout: str
    stderr: str


def validate_repo_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname != "github.com" or parsed.username or parsed.password:
        raise ValueError("Only public GitHub HTTPS repository URLs are allowed.")
    clean_path = parsed.path.rstrip("/")
    if clean_path.endswith(".git"):
        clean_path = clean_path[:-4]
    if not re.fullmatch(r"/[^/]+/[^/]+", clean_path):
        raise ValueError("Use a repository URL like https://github.com/owner/repository.")
    return f"https://github.com{clean_path}.git"


def source_files(workspace: Path) -> dict[str, str]:
    return {
        str(path.relative_to(workspace)).replace("\\", "/"): path.read_text(encoding="utf-8", errors="replace")[:20000]
        for path in workspace.rglob("*")
        if path.is_file() and path.name not in BLOCKED_FILENAMES
        and path.suffix in ALLOWED_EXTENSIONS and ".git" not in path.parts
    }


def run_tests(workspace: Path) -> RunResult:
    timeout = int(os.getenv("RUNNER_TIMEOUT_SECONDS", "120"))
    docker_enabled = os.getenv("DOCKER_ENABLED", "true").lower() == "true"
    docker_bin = shutil.which("docker")
    if docker_enabled and not docker_bin:
        return RunResult("error", None, "", "Docker is required for untrusted repository execution but is not installed or running.")
    if docker_enabled:
        command = ["docker", "run", "--rm", "--network", "none", "--read-only", "--tmpfs", "/tmp", "-v", f"{workspace}:/workspace:rw", "-w", "/workspace", os.getenv("RUNNER_IMAGE", "bughawk-runner:latest"), "pytest", "-q"]
        cwd = None
    else:
        command, cwd = [os.sys.executable, "-m", "pytest", "-q"], workspace
    try:
        completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return RunResult("passed" if completed.returncode == 0 else "failed", completed.returncode, completed.stdout[-12000:], completed.stderr[-12000:])
    except subprocess.TimeoutExpired:
        return RunResult("error", None, "", f"Test run timed out after {timeout} seconds.")


def ai_diagnosis(files: dict[str, str], baseline: RunResult, repo_hint: str) -> dict:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured; diagnosis cannot be generated.")
    prompt = """Diagnose the failing pytest run and return JSON only with keys diagnosis, root_cause, patch (array of path/old/new for existing .py files), suggested_repo_name, and suggested_description.\n\nFILES:\n%s\n\nTEST OUTPUT:\n%s""" % (json.dumps(files), json.dumps(asdict(baseline)))
    payload = {"model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"), "temperature": 0, "response_format": {"type": "json_object"}, "messages": [{"role": "user", "content": prompt}]}
    response = httpx.post("https://api.openai.com/v1/chat/completions", headers={"Authorization": f"Bearer {key}"}, json=payload, timeout=90)
    response.raise_for_status()
    return json.loads(response.json()["choices"][0]["message"]["content"])


def apply_patch(workspace: Path, patch: list[dict]) -> dict[str, tuple[str, str]]:
    changes = {}
    for item in patch:
        relative = Path(item.get("path", ""))
        target = (workspace / relative).resolve()
        if relative.is_absolute() or ".." in relative.parts or relative.suffix not in ALLOWED_EXTENSIONS or workspace.resolve() not in target.parents or not target.exists():
            raise RuntimeError(f"AI patch targets a disallowed file: {relative}")
        current = target.read_text(encoding="utf-8")
        old, new = item.get("old"), item.get("new")
        if not isinstance(old, str) or not isinstance(new, str) or old not in current:
            raise RuntimeError(f"AI patch does not match {relative}.")
        updated = current.replace(old, new, 1)
        target.write_text(updated, encoding="utf-8")
        changes[str(relative).replace("\\", "/")] = (current, updated)
    return changes


def load_history() -> list[dict]:
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def save_history(entry: dict) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    history = load_history()
    history.insert(0, entry)
    HISTORY_FILE.write_text(json.dumps(history[:50], indent=2), encoding="utf-8")


def clone_repository(repository_url: str, destination: Path) -> str:
    clean_url = validate_repo_url(repository_url)
    result = subprocess.run(
        ["git", "clone", "--depth", "1", clean_url, str(destination)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Repository clone failed: {result.stderr[-2000:]}")
    return Path(urlparse(clean_url).path).stem


def analyze(repository_url: str, updates: queue.Queue) -> dict:
    workspace = Path(tempfile.mkdtemp(prefix="bughawk-desktop-"))
    try:
        updates.put("Cloning repository…")
        repo_name = clone_repository(repository_url, workspace)
        updates.put("Collecting supported source files…")
        before = source_files(workspace)
        if not before:
            raise RuntimeError("No supported Python/configuration files were found in this repository.")

        updates.put("Running baseline tests in the isolated runner…")
        baseline = run_tests(workspace)
        if baseline.status == "error":
            raise RuntimeError(baseline.stderr or "The isolated test runner could not start.")

        result = {
            "repository_url": repository_url,
            "repository": repo_name,
            "baseline": asdict(baseline),
            "verification": asdict(baseline),
            "diagnosis": "Baseline tests passed; no repair was required." if baseline.status == "passed" else "",
            "root_cause": "",
            "modified_files": [],
            "diff": "",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if baseline.status == "failed":
            updates.put("Asking the configured analyzer for a diagnosis…")
            diagnosis = ai_diagnosis(before, baseline, repo_hint=repo_name)
            updates.put("Applying and verifying the proposed patch…")
            changes = apply_patch(workspace, diagnosis.get("patch", []))
            verification = run_tests(workspace)
            after = source_files(workspace)
            diff_parts: list[str] = []
            import difflib

            for path, (old, new) in changes.items():
                diff_parts.extend(
                    difflib.unified_diff(
                        old.splitlines(True), new.splitlines(True),
                        fromfile=f"a/{path}", tofile=f"b/{path}",
                    )
                )
            result.update(
                diagnosis=diagnosis.get("diagnosis", ""),
                root_cause=diagnosis.get("root_cause", ""),
                verification=asdict(verification),
                modified_files=list(changes),
                diff="".join(diff_parts),
                patched_file_count=len(after),
            )
        return result
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


class BugHawkApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("BugHawk — Repository Analyzer")
        self.geometry("940x700")
        self.minsize(760, 560)
        self.events: queue.Queue = queue.Queue()
        self.history = load_history()
        self.url_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Paste a public GitHub repository link to begin.")
        self._build_ui()
        self.after(100, self._poll_events)

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=18)
        root.pack(fill="both", expand=True)
        ttk.Label(root, text="BugHawk", font=("Segoe UI", 22, "bold")).pack(anchor="w")
        ttk.Label(root, text="Analyze the next repository from a link", font=("Segoe UI", 11)).pack(anchor="w", pady=(0, 16))

        form = ttk.Frame(root)
        form.pack(fill="x")
        ttk.Label(form, text="GitHub repository URL").pack(anchor="w")
        row = ttk.Frame(form)
        row.pack(fill="x", pady=(5, 0))
        self.url_entry = ttk.Entry(row, textvariable=self.url_var)
        self.url_entry.pack(side="left", fill="x", expand=True)
        self.analyze_button = ttk.Button(row, text="Analyze repository", command=self.start_analysis)
        self.analyze_button.pack(side="left", padx=(8, 0))
        ttk.Label(form, text="Example: https://github.com/owner/repository", foreground="#666").pack(anchor="w", pady=(4, 12))

        ttk.Label(root, textvariable=self.status_var).pack(anchor="w", pady=(0, 8))
        self.progress = ttk.Progressbar(root, mode="indeterminate")
        self.progress.pack(fill="x", pady=(0, 12))

        self.output = ScrolledText(root, wrap="word", state="disabled", font=("Consolas", 10))
        self.output.pack(fill="both", expand=True)
        ttk.Label(root, text=f"Local history: {HISTORY_FILE}", foreground="#666").pack(anchor="w", pady=(8, 0))
        self._write("Results are stored only on this device. API keys and repository contents are not stored.\n")

    def _write(self, text: str) -> None:
        self.output.configure(state="normal")
        self.output.insert("end", text)
        self.output.see("end")
        self.output.configure(state="disabled")

    def start_analysis(self) -> None:
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("Repository link required", "Paste a public GitHub repository URL first.")
            return
        self.analyze_button.configure(state="disabled")
        self.progress.start(10)
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.configure(state="disabled")
        threading.Thread(target=self._worker, args=(url,), daemon=True).start()

    def _worker(self, url: str) -> None:
        try:
            result = analyze(url, self.events)
            self.events.put(("done", result))
        except Exception as exc:  # keep the UI responsive for clone/test failures
            self.events.put(("error", str(exc)))

    def _poll_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                if isinstance(event, str):
                    self.status_var.set(event)
                elif event[0] == "done":
                    self._finish(event[1])
                else:
                    self._fail(event[1])
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _finish(self, result: dict) -> None:
        self.progress.stop()
        self.analyze_button.configure(state="normal")
        self.status_var.set("Analysis complete.")
        save_history(result)
        self._write(json.dumps(result, indent=2))

    def _fail(self, message: str) -> None:
        self.progress.stop()
        self.analyze_button.configure(state="normal")
        self.status_var.set("Analysis failed.")
        self._write(f"\nERROR\n{message}\n")
        messagebox.showerror("BugHawk analysis failed", message)


if __name__ == "__main__":
    BugHawkApp().mainloop()
