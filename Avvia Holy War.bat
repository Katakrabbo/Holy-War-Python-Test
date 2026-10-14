@echo off
setlocal
cd /d "%~dp0"

set "HOLYWAR_PYTHON=%CD%\.venv\Scripts\python.exe"

if not exist "%HOLYWAR_PYTHON%" (
    echo Preparazione dell'ambiente Holy War...
    where py >nul 2>&1
    if errorlevel 1 (
        echo Python non trovato. Installa Python 3.11 o successivo da https://www.python.org/downloads/
        pause
        exit /b 1
    )
    py -3 -m venv ".venv"
    if errorlevel 1 goto :errore
)

"%HOLYWAR_PYTHON%" -B -c "import openpyxl" >nul 2>&1
if errorlevel 1 (
    echo Installazione delle dipendenze...
    "%HOLYWAR_PYTHON%" -m pip install -e .
    if errorlevel 1 goto :errore
)

echo Avvio di Holy War...
"%HOLYWAR_PYTHON%" -B -m holywar.web --cards-json "holywar\data\cards.json"
exit /b %errorlevel%

:errore
echo.
echo Impossibile preparare o avviare Holy War.
pause
exit /b 1
