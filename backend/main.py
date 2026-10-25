import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "sample_project"
ALLOWED_EXTENSIONS = {".py", ".toml", ".ini", ".cfg", ".txt"}
BLOCKED_FILENAMES = {".env", ".env.example"}
app = FastAPI(title="BugHawk API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY", "")


class BlockRepoRequest(BaseModel):
    repo_url: str
    repo_name: str | None = None
    reason: str = "Repository checking blocked"
    description: str = ""
    severity: Literal["low", "medium", "high", "critical"] = "high"
    blocked_by: str = "Community Contributor"
    is_active: bool = True


class CheckRepoRequest(BaseModel):
    repo_url: str


def normalize_repo_identifier(url_or_name: str) -> tuple[str, str]:
    trimmed = url_or_name.strip()
    if trimmed.endswith("/"):
        trimmed = trimmed[:-1]
    if trimmed.endswith(".git"):
        trimmed = trimmed[:-4]
    
    if not trimmed.startswith("http://") and not trimmed.startswith("https://"):
        parts = [p for p in trimmed.split("/") if p]
        if len(parts) >= 2:
            name = f"{parts[0]}/{parts[1]}".lower()
            return f"https://github.com/{name}", name
    
    try:
        parsed = urlparse(trimmed)
        parts = [p for p in parsed.path.strip("/").split("/") if p]
        if len(parts) >= 2:
            name = f"{parts[0]}/{parts[1]}".lower()
            return f"https://github.com/{name}", name
    except Exception:
        pass
    return trimmed, trimmed.lower()


def check_repository_blocked(repo_url: str) -> dict | None:
    """Check if repository is blocked in Supabase."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    normalized_url, repo_name = normalize_repo_identifier(repo_url)
    try:
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
        }
        with httpx.Client(timeout=10) as client:
            resp = client.get(
                f"{SUPABASE_URL}/rest/v1/blocked_repositories",
                headers=headers,
                params={"is_active": "eq.true", "select": "*"}
            )
            if resp.status_code == 200:
                blocked_list = resp.json()
                for item in blocked_list:
                    item_url = item.get("repo_url", "").lower().rstrip("/")
                    if item_url.endswith(".git"):
                        item_url = item_url[:-4]
                    item_name = item.get("repo_name", "").lower()
                    if item_name == repo_name or item_url == normalized_url.lower():
                        return item
    except Exception as exc:
        print(f"[Supabase] Warning: Error checking blocked repositories: {exc}")
    return None



class DebugRequest(BaseModel):
    source: Literal["sample", "github", "auto"] = "auto"
    repository_url: str | None = None
    auto_deploy: bool = True
    deploy_private: bool = False


class RunResult(BaseModel):
    status: Literal["passed", "failed", "error"]
    exit_code: int | None
    stdout: str
    stderr: str


def validate_repo_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname != "github.com" or parsed.username or parsed.password:
        raise HTTPException(400, "Only public GitHub HTTPS repository URLs are allowed.")
    clean_path = parsed.path.rstrip("/")
    if clean_path.endswith(".git"):
        clean_path = clean_path[:-4]
    if not re.fullmatch(r"/[^/]+/[^/]+", clean_path):
        raise HTTPException(400, "Use a repository URL like https://github.com/owner/repository.")
    return f"https://github.com{clean_path}.git"


def run_tests(workspace: Path, is_untrusted: bool = False) -> RunResult:
    timeout = int(os.getenv("RUNNER_TIMEOUT_SECONDS", "120"))
    docker_enabled = os.getenv("DOCKER_ENABLED", "true").lower() == "true"
    docker_bin = shutil.which("docker")

    if is_untrusted and docker_enabled and not docker_bin:
        return RunResult(
            status="error",
            exit_code=None,
            stdout="",
            stderr="Docker is required for untrusted repository execution but is not installed or running on this system.",
        )

    if docker_enabled and docker_bin:
        command = [
            "docker", "run", "--rm",
            "--network", "none",
            "--read-only",
            "--tmpfs", "/tmp",
            "--memory", os.getenv("RUNNER_MEMORY_LIMIT", "512m"),
            "--cpus", os.getenv("RUNNER_CPU_LIMIT", "1"),
            "-v", f"{workspace}:/workspace:rw",
            "-w", "/workspace",
            os.getenv("RUNNER_IMAGE", "bughawk-runner:latest"),
            "pytest", "-q",
        ]
        cwd = None
    else:
        command = [sys.executable, "-m", "pytest", "-q"]
        cwd = workspace

    try:
        completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        status = "passed" if completed.returncode == 0 else "failed"
        return RunResult(status=status, exit_code=completed.returncode, stdout=completed.stdout[-12000:], stderr=completed.stderr[-12000:])
    except subprocess.TimeoutExpired as exc:
        return RunResult(status="error", exit_code=None, stdout=(exc.stdout or "")[-12000:] if isinstance(exc.stdout, str) else "", stderr=f"Test run timed out after {timeout} seconds.")
    except Exception as exc:
        return RunResult(status="error", exit_code=None, stdout="", stderr=str(exc))


def source_files(workspace: Path) -> dict[str, str]:
    result = {}
    for path in workspace.rglob("*"):
        if path.is_file() and path.name not in BLOCKED_FILENAMES and path.suffix in ALLOWED_EXTENSIONS and ".git" not in path.parts:
            result[str(path.relative_to(workspace)).replace("\\", "/")] = path.read_text(encoding="utf-8", errors="replace")[:20000]
    return result


class DeployRequest(BaseModel):
    repo_name: str
    description: str = "Patched and verified by BugHawk AI"
    private: bool = False
    files: dict[str, str]


def github_headers() -> dict[str, str]:
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise HTTPException(503, "GITHUB_TOKEN is not configured; cannot use GitHub.")
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


def discover_repository() -> str:
    headers = github_headers()
    try:
        response = httpx.get("https://api.github.com/user/repos", headers=headers, params={"sort": "updated", "direction": "desc", "per_page": 1, "affiliation": "owner,collaborator"}, timeout=20)
        response.raise_for_status()
        repositories = response.json()
        if not repositories:
            raise HTTPException(400, "No GitHub repositories were found for the authenticated account.")
        return validate_repo_url(repositories[0]["html_url"])
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"Failed to discover a GitHub repository: {exc}") from exc


def ai_diagnosis(files: dict[str, str], baseline: RunResult, repo_hint: str = "project") -> dict:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise HTTPException(503, "OPENAI_API_KEY is not configured; diagnosis cannot be generated.")
    prompt = """You are BugHawk. Diagnose the failing pytest run and propose the smallest safe patch.
Return JSON only with keys:
- diagnosis: explanation of the issue
- root_cause: root cause of the failure
- patch: array of {path, old, new} modifying only existing .py files
- suggested_repo_name: short, clean, lowercase hyphenated repository name for publishing the fix, e.g. "%s-fixed"
- suggested_description: concise 1-sentence description of the fixed project

FILES:
%s

TEST OUTPUT:
%s""" % (repo_hint, json.dumps(files), json.dumps(baseline.model_dump()))
    payload = {"model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"), "temperature": 0, "response_format": {"type": "json_object"}, "messages": [{"role": "user", "content": prompt}]}
    try:
        response = httpx.post("https://api.openai.com/v1/chat/completions", headers={"Authorization": f"Bearer {key}"}, json=payload, timeout=90)
        response.raise_for_status()
        return json.loads(response.json()["choices"][0]["message"]["content"])
    except (httpx.HTTPError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(502, f"AI diagnosis failed: {exc}") from exc


def apply_patch(workspace: Path, patch: list[dict]) -> dict[str, tuple[str, str]]:
    changes = {}
    for item in patch:
        relative = Path(item.get("path", ""))
        if relative.is_absolute() or ".." in relative.parts or relative.suffix not in ALLOWED_EXTENSIONS:
            raise HTTPException(400, "AI patch contains a disallowed path.")
        target = (workspace / relative).resolve()
        if workspace.resolve() not in target.parents or not target.exists():
            raise HTTPException(400, f"AI patch targets an invalid file: {relative}")
        old, new = item.get("old"), item.get("new")
        if not isinstance(old, str) or not isinstance(new, str):
            raise HTTPException(400, f"AI patch has invalid format for {relative}.")
        current = target.read_text(encoding="utf-8")
        current_norm = current.replace("\r\n", "\n")
        old_norm = old.replace("\r\n", "\n")
        new_norm = new.replace("\r\n", "\n")
        if old_norm not in current_norm:
            raise HTTPException(400, f"AI patch does not match {relative}.")
        updated_norm = current_norm.replace(old_norm, new_norm, 1)
        updated = updated_norm.replace("\n", "\r\n") if "\r\n" in current else updated_norm
        target.write_text(updated, encoding="utf-8")
        changes[str(relative).replace("\\", "/")] = (current_norm, updated_norm)
    return changes


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/debug")
def debug(request: DebugRequest):
    source = "sample" if request.source == "sample" else "github"
    workspace = Path(tempfile.mkdtemp(prefix="bughawk-"))
    is_untrusted = source == "github"
    repo_hint = "discount-calculator"
    try:
        if source == "sample":
            shutil.copytree(SAMPLE, workspace, dirs_exist_ok=True)
        else:
            url = validate_repo_url(request.repository_url) if request.repository_url else discover_repository()
            # Enforce Blocklist Check
            blocked_entry = check_repository_blocked(url)
            if blocked_entry:
                reason = blocked_entry.get("reason", "Prohibited by repository security policy")
                severity = blocked_entry.get("severity", "high")
                raise HTTPException(
                    status_code=403,
                    detail=f"Repository checking is blocked for '{url}'. Reason: {reason} (Severity: {severity.upper()}). This repository is prohibited from being checked."
                )
            clean_name = Path(urlparse(url).path).stem
            if clean_name:
                repo_hint = clean_name
            clone = subprocess.run(["git", "clone", "--depth", "1", url, str(workspace)], capture_output=True, text=True, timeout=60)
            if clone.returncode != 0:
                raise HTTPException(400, f"Repository clone failed: {clone.stderr[-2000:]}")
        before = source_files(workspace)
        baseline = run_tests(workspace, is_untrusted=is_untrusted)
        if baseline.status == "error":
            raise HTTPException(500, baseline.stderr or "Failed to run baseline tests.")
        if baseline.status != "failed":
            result = {"status": "complete", "diagnosis": "Baseline tests did not fail.", "root_cause": "", "baseline": baseline.model_dump(), "verification": baseline.model_dump(), "diff": "", "modified_files": [], "patched_files": before, "suggested_repo_name": f"{repo_hint}-fixed", "suggested_description": f"Verified repository for {repo_hint}"}
            if request.auto_deploy:
                result["deployment"] = deploy_files(result["suggested_repo_name"], result["suggested_description"], request.deploy_private, before)
            return result
        diagnosis = ai_diagnosis(before, baseline, repo_hint=repo_hint)
        changes = apply_patch(workspace, diagnosis.get("patch", []))
        verification = run_tests(workspace, is_untrusted=is_untrusted)
        after_files = source_files(workspace)
        diff_parts = []
        for path, (old, new) in changes.items():
            diff_parts.extend(difflib.unified_diff(old.splitlines(True), new.splitlines(True), fromfile=f"a/{path}", tofile=f"b/{path}"))
        
        suggested_repo_name = diagnosis.get("suggested_repo_name") or f"{repo_hint}-fixed"
        suggested_description = diagnosis.get("suggested_description") or f"Patched and verified version of {repo_hint} by BugHawk AI."
        
        result = {
            "status": "complete",
            "diagnosis": diagnosis.get("diagnosis", ""),
            "root_cause": diagnosis.get("root_cause", ""),
            "baseline": baseline.model_dump(),
            "verification": verification.model_dump(),
            "diff": "".join(diff_parts),
            "modified_files": list(changes),
            "patched_files": after_files,
            "suggested_repo_name": suggested_repo_name,
            "suggested_description": suggested_description,
        }
        if verification.status == "passed" and request.auto_deploy:
            result["deployment"] = deploy_files(suggested_repo_name, suggested_description, request.deploy_private, after_files)
        return result
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


@app.post("/api/deploy")
def deploy_repo(request: DeployRequest):
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise HTTPException(503, "GITHUB_TOKEN is not configured; cannot deploy to GitHub.")
    
    clean_name = re.sub(r"[^a-zA-Z0-9._-]", "-", request.repo_name.strip()).strip(".-")
    if not clean_name:
        raise HTTPException(400, "Invalid repository name.")
    
    headers = github_headers()
    
    # 1. Get authenticated user login
    try:
        user_res = httpx.get("https://api.github.com/user", headers=headers, timeout=15)
        user_res.raise_for_status()
        username = user_res.json().get("login")
    except Exception as exc:
        raise HTTPException(502, f"Failed to authenticate with GitHub: {exc}")
        
    # 2. Create the repository on GitHub
    repo_payload = {
        "name": clean_name,
        "description": request.description or "Patched and verified by BugHawk AI",
        "private": request.private,
        "auto_init": False,
    }
    try:
        create_res = httpx.post("https://api.github.com/user/repos", headers=headers, json=repo_payload, timeout=20)
        if create_res.status_code == 422:
            detail = create_res.json().get("message", "Repository may already exist.")
            errors = create_res.json().get("errors", [])
            err_msg = "; ".join([e.get("message", "") for e in errors]) if errors else detail
            raise HTTPException(400, f"GitHub repository creation failed: {err_msg or detail}")
        create_res.raise_for_status()
        repo_data = create_res.json()
        html_url = repo_data.get("html_url", f"https://github.com/{username}/{clean_name}")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"GitHub repository creation failed: {exc}")
        
    # 3. Push files to the new repository
    temp_dir = Path(tempfile.mkdtemp(prefix="bughawk-deploy-"))
    try:
        for path_str, content in request.files.items():
            relative = Path(path_str)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or relative.name in BLOCKED_FILENAMES
            ):
                raise HTTPException(400, f"Deployment contains a disallowed path: {path_str}")
            file_path = (temp_dir / relative).resolve()
            if temp_dir.resolve() not in file_path.parents:
                raise HTTPException(400, f"Deployment contains a path outside the repository: {path_str}")
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            
        if "README.md" not in request.files and "readme.md" not in request.files:
            (temp_dir / "README.md").write_text(
                f"# {clean_name}\n\n{request.description}\n\n*Patched and verified by BugHawk AI.*",
                encoding="utf-8",
            )
            
        subprocess.run(["git", "init", "-b", "main"], cwd=temp_dir, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "BugHawk"], cwd=temp_dir, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "bughawk@agent.local"], cwd=temp_dir, capture_output=True, check=True)
        subprocess.run(["git", "add", "."], cwd=temp_dir, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit: patched and verified by BugHawk"], cwd=temp_dir, capture_output=True, check=True)
        
        push_url = f"https://x-access-token:{token}@github.com/{username}/{clean_name}.git"
        push_res = subprocess.run(
            ["git", "-c", "credential.helper=", "push", "-u", push_url, "main"],
            cwd=temp_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if push_res.returncode != 0:
            raise HTTPException(502, f"Git push failed: {push_res.stderr[-1000:]}")
            
        return {
            "status": "success",
            "repo_url": html_url,
            "repo_name": clean_name,
            "owner": username,
        }
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def deploy_files(repo_name: str, description: str, private: bool, files: dict[str, str]) -> dict:
    return deploy_repo(DeployRequest(repo_name=repo_name, description=description, private=private, files=files))


@app.get("/api/blocked")
def get_blocked_repositories():
    if not SUPABASE_URL or not SUPABASE_KEY:
        return []
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(
                f"{SUPABASE_URL}/rest/v1/blocked_repositories",
                headers=headers,
                params={"select": "*", "order": "created_at.desc"}
            )
            if resp.status_code == 200:
                return resp.json()
            raise HTTPException(resp.status_code, resp.text)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"Failed to retrieve blocked repositories: {exc}")


@app.post("/api/check-repo")
def check_repo_endpoint(request: CheckRepoRequest):
    blocked_entry = check_repository_blocked(request.repo_url)
    if blocked_entry:
        return {
            "blocked": True,
            "message": f"Checking is BLOCKED for '{blocked_entry.get('repo_name', request.repo_url)}'.",
            "rule": blocked_entry
        }
    return {
        "blocked": False,
        "message": "Repository checking is ALLOWED."
    }


@app.post("/api/blocked")
def add_blocked_repository(request: BlockRepoRequest):
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise HTTPException(503, "Supabase credentials are not configured in environment.")
    normalized_url, repo_name = normalize_repo_identifier(request.repo_url)
    repo_name = request.repo_name or repo_name
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    payload = {
        "repo_url": normalized_url,
        "repo_name": repo_name,
        "reason": request.reason,
        "description": request.description,
        "severity": request.severity,
        "blocked_by": request.blocked_by,
        "is_active": request.is_active,
    }
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(
                f"{SUPABASE_URL}/rest/v1/blocked_repositories",
                headers=headers,
                json=payload
            )
            if resp.status_code in (200, 201):
                return resp.json()
            if resp.status_code == 409 or "duplicate key" in resp.text:
                raise HTTPException(409, f"Repository '{repo_name}' is already in the blocklist.")
            raise HTTPException(resp.status_code, resp.text)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"Failed to add blocked repository: {exc}")


@app.patch("/api/blocked/{repo_id}")
def toggle_blocked_repository(repo_id: str, updates: dict):
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise HTTPException(503, "Supabase credentials are not configured in environment.")
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.patch(
                f"{SUPABASE_URL}/rest/v1/blocked_repositories?id=eq.{repo_id}",
                headers=headers,
                json=updates
            )
            if resp.status_code in (200, 204):
                return resp.json() if resp.text else {"status": "updated"}
            raise HTTPException(resp.status_code, resp.text)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"Failed to update blocked repository: {exc}")


@app.delete("/api/blocked/{repo_id}")
def delete_blocked_repository(repo_id: str):
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise HTTPException(503, "Supabase credentials are not configured in environment.")
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.delete(
                f"{SUPABASE_URL}/rest/v1/blocked_repositories?id=eq.{repo_id}",
                headers=headers
            )
            if resp.status_code in (200, 204):
                return {"status": "deleted"}
            raise HTTPException(resp.status_code, resp.text)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"Failed to delete blocked repository: {exc}")


