$ErrorActionPreference = "Stop"

# Build a single-file Windows GUI executable. The app reads only process
# environment variables; it never loads .env or .env.example files.
py -3 -m PyInstaller --noconfirm --clean --onefile --windowed --name BugHawk `
  --paths . `
  --exclude-module IPython --exclude-module numpy --exclude-module matplotlib `
  --exclude-module PySide6 --exclude-module shiboken6 --exclude-module pytest `
  --exclude-module jedi --exclude-module parso --exclude-module nbformat `
  --exclude-module zmq --exclude-module PIL --exclude-module astroid `
  desktop_app.py

Write-Host "Built dist\\BugHawk.exe"
