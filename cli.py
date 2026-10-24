"""BugHawk CLI - Interactive terminal tool for AI debugging and GitHub redeployment."""

import argparse
import os
import sys
import httpx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

API_URL = os.getenv("NEXT_PUBLIC_API_URL", "http://127.0.0.1:8000")


def print_banner():
    print("\n" + "=" * 70)
    print("   🦅 BugHawk: AI Debugging & GitHub Redeployment CLI")
    print("=" * 70 + "\n")


def run_cli():
    parser = argparse.ArgumentParser(description="BugHawk AI Debugger & GitHub Publisher")
    parser.add_argument("--source", choices=["auto", "sample", "github"], default=None, help="Source of repository")
    parser.add_argument("--repo", default=None, help="Public GitHub repository URL (if source=github)")
    parser.add_argument("--non-interactive", action="store_true", help="Accept all AI defaults without prompting")
    args = parser.parse_args()

    print_banner()

    source = args.source
    repo_url = args.repo

    if not source:
        print("Select project source:")
        print("  [1] Find my latest GitHub repository automatically")
        print("  [2] Bundled sample project (discount-calculator)")
        print("  [3] Public GitHub repository URL")
        choice = input("\nEnter choice [1, 2 or 3] (default: 1): ").strip()
        if choice == "3":
            source = "github"
            repo_url = input("Enter public GitHub repository URL (e.g. https://github.com/owner/repo): ").strip()
            while not repo_url:
                repo_url = input("Repository URL cannot be empty. Enter URL: ").strip()
        elif choice == "2":
            source = "sample"
        else:
            source = "auto"

    print(f"\n[1/4] Reproducing bug and executing baseline tests ({source})...")

    try:
        debug_res = httpx.post(
            f"{API_URL}/api/debug",
            json={"source": source, "repository_url": repo_url or None, "auto_deploy": True},
            timeout=120,
        )
    except httpx.ConnectError:
        print(f"\n❌ Error: Could not connect to BugHawk API server at {API_URL}.")
        print("Please ensure the backend is running with: py -m uvicorn backend.main:app --port 8000")
        sys.exit(1)

    if debug_res.status_code != 200:
        print(f"\n❌ Debugging failed ({debug_res.status_code}): {debug_res.text}")
        sys.exit(1)

    result = debug_res.json()

    print("\n" + "-" * 70)
    print("   📋 BASELINE TEST RESULTS")
    print("-" * 70)
    baseline = result.get("baseline", {})
    print(f"Status: {baseline.get('status', 'unknown').upper()}")
    print("Output:")
    print((baseline.get("stdout") or baseline.get("stderr") or "No output").strip())

    print("\n[2/4] OpenAI root-cause analysis and diagnosis...")
    print("\n" + "-" * 70)
    print("   🧠 AI DIAGNOSIS & PROPOSED FIX")
    print("-" * 70)
    print(f"Root Cause: {result.get('root_cause')}")
    print(f"Diagnosis : {result.get('diagnosis')}")
    print("\nUnified Diff:")
    print(result.get("diff") or "No diff produced.")

    print("\n[3/4] Validating and applying safe patch...")
    print(f"Modified files: {', '.join(result.get('modified_files', []))}")

    print("\n[4/4] Executing verification tests in isolated workspace...")
    verification = result.get("verification", {})
    verif_status = verification.get("status", "unknown")
    print(f"Verification Status: {verif_status.upper()}")

    if verif_status != "passed":
        print("\n❌ Fix could not be verified by tests.")
        print((verification.get("stdout") or verification.get("stderr") or "").strip())
        sys.exit(1)

    print("\n✅ Bug successfully reproduced, diagnosed, patched, and verified!")

    deployment = result.get("deployment")
    if deployment:
        print("\n🎉 Repository automatically redeployed to GitHub!")
        print(f"Repository URL : {deployment.get('repo_url')}")
        return

    print("\n⚠️ No automatic deployment was returned. Check GITHUB_TOKEN and the API response.")
    return


if __name__ == "__main__":
    run_cli()
