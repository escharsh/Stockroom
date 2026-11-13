@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  python -m venv .venv
  if errorlevel 1 goto failed
)
.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto failed
.venv\Scripts\python.exe seed_demo.py
if errorlevel 1 goto failed
.venv\Scripts\python.exe seed_workflows.py
if errorlevel 1 goto failed
.venv\Scripts\python.exe serve.py --open
pause
exit /b
:failed
echo Setup failed. Check that Python 3.11 or newer and internet access are available.
pause
exit /b 1
