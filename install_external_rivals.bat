@echo off
title CotatQ v1.2 External Rival Installer
echo ============================================================
echo Installing core benchmark dependencies...
echo ============================================================
python -m pip install -r requirements_core.txt
if errorlevel 1 goto :fail

echo.
echo ============================================================
echo Installing dedicated tensor-network competitors...
echo cotengra + quimb
echo ============================================================
python -m pip install -r requirements_external.txt
if errorlevel 1 goto :optional_fail

echo.
echo Installation complete.
python doctor_v12.py
pause
exit /b 0

:optional_fail
echo.
echo WARNING: cotengra/quimb installation failed.
echo The doctor will record them as unavailable.
echo A strong-rival verdict will require sufficient advanced rival coverage.
python doctor_v12.py
pause
exit /b 1

:fail
echo Core dependency installation failed.
pause
exit /b 1
