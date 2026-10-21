@echo off
echo ========================================================
echo    Starting BIDS Platform (Backend + Frontend)
echo ========================================================
echo.

echo Starting FastAPI Backend on http://127.0.0.1:8000 ...
start "BIDS Backend (FastAPI)" cmd /k "cd /d %~dp0backend && ..\.venv\Scripts\python.exe -m uvicorn main:app --reload --host 127.0.0.1 --port 8000"

echo Starting Next.js Frontend on http://localhost:3000 ...
start "BIDS Frontend (Next.js)" cmd /k "cd /d %~dp0frontend && npm run dev"

echo.
echo ========================================================
echo    Both servers have been launched in separate windows!
echo    - Frontend: http://localhost:3000
echo    - Backend:  http://127.0.0.1:8000 (API Docs: http://127.0.0.1:8000/docs)
echo ========================================================
pause
