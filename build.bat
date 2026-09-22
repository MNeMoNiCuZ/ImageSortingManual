@echo off
setlocal
cd /d "%~dp0"

if exist "venv\Scripts\python.exe" (
    set "BUILD_PYTHON=venv\Scripts\python.exe"
) else (
    set "BUILD_PYTHON=py"
)

%BUILD_PYTHON% build.py --onefile
if errorlevel 1 exit /b %errorlevel%

copy /Y "src\dist\Trimage.exe" "Trimage.exe" >nul
if errorlevel 1 exit /b %errorlevel%

echo Built Trimage.exe
