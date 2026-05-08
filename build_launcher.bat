@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo  Building Plamma Launcher...
echo.

REM Check PyInstaller is available
python -m PyInstaller --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  ERROR: PyInstaller not found. Run:  pip install pyinstaller
    pause
    exit /b 1
)

REM Build the launcher exe
REM   --onefile        = single self-contained exe
REM   --icon           = embed icon.ico
REM   --name Launcher  = output filename
REM   --console        = keep console window (needed to show startup progress)
REM   --distpath .     = place Launcher.exe in the project root, not dist/
REM   --hidden-import  = ensure socks support for Tor routing check
python -m PyInstaller ^
    --onefile ^
    --icon=icon.ico ^
    --name=Launcher ^
    --console ^
    --distpath . ^
    --hidden-import=socks ^
    --hidden-import=requests ^
    launcher.py

if %errorlevel% neq 0 (
    echo.
    echo  Build failed.
    pause
    exit /b 1
)

echo.
echo  Done. Launcher.exe is in the project root.
echo  Double-click Launcher.exe to start Plamma.
echo.
pause
