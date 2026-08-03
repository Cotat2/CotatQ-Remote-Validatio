@echo off
title CotatQ v1.2.1 Strong Rival STANDARD
echo ============================================================
echo CotatQ v1.2.1 - STRONG RIVAL STANDARD
echo Adapter-only compatibility patch.
echo CotatQ/cases/thresholds remain frozen.
echo ============================================================
python verify_patch_v121.py
if errorlevel 1 goto :fail

python doctor_v121.py
if errorlevel 1 goto :doctor_fail

echo.
echo Running the SAME locked 36-case Strong Rival STANDARD...
python independent_validation_v121.py --suite strong --mode standard --runner-label local-or-external
if errorlevel 1 goto :fail

python bundle_results_v121.py

echo.
echo v1.2.1 STRONG STANDARD COMPLETE.
pause
exit /b 0

:doctor_fail
echo.
echo STRICT DOCTOR FAILED.
echo Benchmark has NOT been started.
pause
exit /b 1

:fail
echo.
echo VALIDATION STOPPED DUE TO ERROR.
pause
exit /b 1
