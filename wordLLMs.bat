@echo off
.venv\Scripts\Activate.ps1
uvicorn src.backend.main:app --host 0.0.0.0 --port 3000