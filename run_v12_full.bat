@echo off
title CotatQ v1.2 Independent Validation - FULL
echo ============================================================
echo CotatQ v1.2 FULL
echo 270-case reproduction + 90-case strong rival challenge
echo This can take a long time, especially with path optimizers.
echo ============================================================
python verify_freeze_v12.py
if errorlevel 1 goto :fail

python doctor_v12.py

echo.
echo [1/2] Running locked reproduction FULL...
python independent_validation_v12.py --suite reproduction --mode full --runner-label local-or-external
if errorlevel 1 goto :fail

echo.
echo [2/2] Running locked strong-rival FULL...
python independent_validation_v12.py --suite strong --mode full --runner-label local-or-external
if errorlevel 1 goto :fail

python bundle_results_v12.py
echo.
echo FULL COMPLETE.
pause
exit /b 0

:fail
echo.
echo VALIDATION STOPPED DUE TO ERROR.
pause
exit /b 1
