@echo off
REM Start the BizDev Hub development server (double-click this file, or run "start.bat" in a terminal).
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Virtual environment not found. Create it with:  python -m venv .venv  then  .venv\Scripts\python.exe -m pip install -r requirements-dev.txt
  pause
  exit /b 1
)
echo Applying any pending database migrations...
".venv\Scripts\python.exe" manage.py migrate --noinput
echo.
echo BizDev Hub is starting at http://127.0.0.1:8000/   (press Ctrl+C to stop)
start "" http://127.0.0.1:8000/
".venv\Scripts\python.exe" manage.py runserver 127.0.0.1:8000
pause
