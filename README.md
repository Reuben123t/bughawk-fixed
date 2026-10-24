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

Provide `OPENAI_API_KEY` and `GITHUB_TOKEN` through the process environment for AI diagnosis and GitHub publishing. BugHawk does not load `.env` or `.env.example` files. Without the required variables, it returns a clear configuration error rather than fabricating a result. Docker is recommended for repository execution; local execution is disabled unless `DOCKER_ENABLED=false`.

Build the isolated runner image before using Docker:

```powershell
docker build -t bughawk-runner:latest runner
```
