@echo off
rem Erstellt dist\Schalk\Schalk.exe (Ordner-Build, startet schneller als eine Einzeldatei)
setlocal
cd /d "%~dp0"

if not exist venv (
    python -m venv venv || goto :error
)
call venv\Scripts\activate.bat || goto :error
python -m pip install --upgrade pip || goto :error
python -m pip install -r requirements-dev.txt || goto :error

python -m pytest -q tests || goto :error

pyinstaller --noconfirm --clean --windowed --name Schalk ^
    --collect-all saxonche ^
    --collect-data facturx ^
    --collect-data drafthorse ^
    --collect-data reportlab ^
    --collect-data stdnum ^
    --collect-data qfluentwidgets ^
    run.py || goto :error

echo.
echo Fertig: dist\Schalk\Schalk.exe
exit /b 0

:error
echo.
echo Build fehlgeschlagen.
exit /b 1
