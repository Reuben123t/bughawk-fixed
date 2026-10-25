# BugHawk & RepoBlock 🛡️

An AI-assisted code analysis, autonomous debugging, code generation, and repository policy enforcement platform.

## ✨ Features

- 🔍 **GitHub Scanner & Discovery**: Search GitHub users by username or email, browse their public repositories, analyze codebases for bugs or upgrade opportunities, and autonomously patch them.
- ⚡ **AI Code Creator & Upgrader**: Generate production-ready projects from text descriptions with unit tests, READMEs, and configurations, and automatically deploy them to your GitHub account as brand new repositories.
- 🔬 **Autonomous VM Engine**: Live test runner simulation showcasing repository cloning, baseline test failure detection, AST root-cause analysis, and atomic verified diff application.
- 🛑 **RepoBlock / Community Shield**: Proactive security gate preventing unauthorized or malicious checking of sensitive repositories. Integrated with Supabase with real-time rule synchronization.
- 🛠️ **BugHawk Core Workflow**: Clone public repos, run pytest/vitest suites inside isolated containers, generate AI patches, and verify bug fixes before deployment.
- 🖥️ **Desktop App**: Optional native Windows GUI built with PySide6 and packaged with PyInstaller.

---

## 🚀 Quick Start

### 1. Prerequisites
- **Python 3.11+**
- **Node.js 18+**
- (Optional) **Docker Desktop** for containerized test execution

### 2. Configure Environment Variables
Copy `.env.example` to `.env` (backend) and `frontend/.env.local` (frontend):

```powershell
cp .env.example .env
cp .env.example frontend/.env.local
```

Fill in your API credentials:
- `OPENAI_API_KEY`: Required for AI diagnosis and code generation.
- `GITHUB_TOKEN`: GitHub personal access token (with `repo` scope) for uploading new repositories.
- `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY`: Supabase project for repository blocklist synchronization.

### 3. Backend Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload --port 8000
```

### 4. Frontend Setup

In a separate terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

---

## 🖥️ Building the Windows Desktop App

```powershell
py -m pip install pyinstaller pyside6
.\build_windows.ps1
```

The resulting standalone executable will be located in `dist\BugHawk.exe`.

---

## 🐳 Isolated Runner Image (Docker)

```powershell
docker build -t bughawk-runner:latest runner
```

---

## 📄 License
MIT License
