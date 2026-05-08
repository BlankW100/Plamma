@echo off
cd /d "%~dp0"
chcp 65001 >nul
title Plamma -- Starting
cls

:: ============================================================
::  CONFIGURATION — edit these two lines to match your system
:: ============================================================
if not defined TOR_EXE  set "TOR_EXE=%APPDATA%\tor\tor\tor.exe"
if not defined TOR_TORRC set "TOR_TORRC=%APPDATA%\tor\torrc"
:: ============================================================

echo.
echo  ================================================
echo    P L A M M A  --  Private  Local  AI
echo  ================================================
echo.

:: ===========================================================
::  [1/3]  TOR
:: ===========================================================

:: Check if Tor circuits are already ready (not just the port)
python "%~dp0tor_wait.py" >nul 2>&1
if %errorlevel%==0 (
    echo  [1/3]  Tor    ....  already running
    goto ollama_check
)

:: Start Tor if port is not even open yet
call :port_open 9050
if %errorlevel%==1 (
    echo  [1/3]  Tor    ....  starting
    start "Tor [Plamma]" /min "%TOR_EXE%" -f "%TOR_TORRC%"
) else (
    echo  [1/3]  Tor    ....  building circuits
)

:: Wait until tor_wait.py confirms circuits are actually ready
:tor_circuit_wait
timeout /t 4 /nobreak >nul
python "%~dp0tor_wait.py" >nul 2>&1
if %errorlevel%==1 goto tor_circuit_wait

echo  [1/3]  Tor    ....  ready

:: ===========================================================
::  [2/3]  OLLAMA
:: ===========================================================
:ollama_check
call :port_open 11434
if %errorlevel%==0 (
    echo  [2/3]  Ollama ....  already running
    goto launch
)

echo  [2/3]  Ollama ....  starting in background
start "Ollama [Plamma]" /min ollama serve

:ollama_wait
timeout /t 2 /nobreak >nul
call :port_open 11434
if %errorlevel%==1 goto ollama_wait
echo  [2/3]  Ollama ....  ready

:: ===========================================================
::  [3/3]  PLAMMA
:: ===========================================================
:launch
echo  [3/3]  Plamma ....  launching
echo.
title Plamma
"%~dp0dist\Plamma.exe"

echo.
echo  Session ended.
pause
goto :eof

:: --- subroutine: returns 0 if port is listening, 1 if not ---
:port_open
powershell -noprofile -command "try{$c=New-Object Net.Sockets.TcpClient;$r=$c.BeginConnect('127.0.0.1',%1,$null,$null);if($r.AsyncWaitHandle.WaitOne(800)){$c.EndConnect($r);$c.Close();exit 0}exit 1}catch{exit 1}" >nul 2>&1
exit /b %errorlevel%
