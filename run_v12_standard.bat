@echo off
title CotatQ v1.2 Independent Validation - STANDARD
echo ============================================================
echo CotatQ v1.2 STANDARD
echo Frozen algorithm + locked protocol
echo ============================================================
python verify_freeze_v12.py
if errorlevel 1 goto :fail

python doctor_v12.py

echo.
echo [1/2] Running locked reproduction STANDARD...
python independent_validation_v12.py --suite reproduction --mode standard --runner-label local-or-external
if errorlevel 1 goto :fail

echo.
echo [2/2] Running locked strong-rival STANDARD...
python independent_validation_v12.py --suite strong --mode standard --runner-label local-or-external
if errorlevel 1 goto :fail

python bundle_results_v12.py
echo.
echo STANDARD COMPLETE.
pause
exit /b 0

:fail
echo.
echo VALIDATION STOPPED DUE TO ERROR.
pause
exit /b 1
