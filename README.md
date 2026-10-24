# BugHawk

Minimal AI-assisted debugging platform. The MVP accepts the bundled discount-calculator sample or a public GitHub HTTPS URL, runs baseline tests, asks OpenAI for a structured diagnosis and patch, applies only validated file patches in a disposable workspace, and runs tests again.

## Run

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload --port 8000
```

In another terminal:

```powershell
cd frontend
npm install
npm run dev
```

## Windows desktop app

Install PyInstaller and build the native app:

```powershell
py -3 -m pip install pyinstaller
.\build_windows.ps1
```

The output is `dist\BugHawk.exe`. Paste a public GitHub repository link into the app to clone, test, diagnose, and verify it. Analysis history is stored locally at `%LOCALAPPDATA%\BugHawk\history.json`. The app does not read `.env` or `.env.example`; provide required API credentials through the process environment before launching it.

Provide `OPENAI_API_KEY` and `GITHUB_TOKEN` through the process environment for AI diagnosis and GitHub publishing. BugHawk does not load `.env` or `.env.example` files. Without the required variables, it returns a clear configuration error rather than fabricating a result. Docker is recommended for repository execution; local execution is disabled unless `DOCKER_ENABLED=false`.

Build the isolated runner image before using Docker:

```powershell
docker build -t bughawk-runner:latest runner
```
