@echo off
rem Erstellt dist\Schalk\Schalk.exe (Ordner-Build, startet schneller als eine Einzeldatei)
setlocal
cd /d "%~dp0"

if not exist venv (
    rem Without the Python launcher (e.g. on the GitHub build server) the python on the PATH is used
    py -3.14 -m venv venv 2>nul || python -m venv venv || goto :error
)
call venv\Scripts\activate.bat || goto :error
python -m pip install --upgrade pip || goto :error
python -m pip install -r requirements-dev.txt || goto :error

python -m pytest -q tests
if errorlevel 1 (
    echo Tests fehlgeschlagen ^(Exitcode %errorlevel%^)
    goto :error
)

pyinstaller --noconfirm --clean --windowed --name Schalk ^
    --collect-all saxonche ^
    --collect-data facturx ^
    --collect-data drafthorse ^
    --collect-data reportlab ^
    --collect-data stdnum ^
    --collect-data qfluentwidgets ^
    --add-data "src\resources;src\resources" ^
    run.py
if errorlevel 1 (
    echo PyInstaller fehlgeschlagen ^(Exitcode %errorlevel%^)
    goto :error
)

echo.
echo Fertig: dist\Schalk\Schalk.exe
exit /b 0

:error
echo.
echo Build fehlgeschlagen.
exit /b 1
