@echo off
title CotatQ v1.2.2 Strong Rival STANDARD
echo ============================================================
echo CotatQ v1.2.2 - STRONG RIVAL STANDARD
echo Exact Aer MPS compatibility patch.
echo CotatQ/cases/thresholds/timeouts remain frozen.
echo ============================================================
python verify_patch_v122.py
if errorlevel 1 goto :fail
python doctor_v122.py
if errorlevel 1 goto :doctor_fail
echo.
echo Running SAME locked 36-case Strong Rival STANDARD...
python independent_validation_v122.py --suite strong --mode standard --runner-label local-or-external
if errorlevel 1 goto :fail
echo.
echo STANDARD COMPLETE.
pause
exit /b 0
:doctor_fail
echo.
echo STRICT DOCTOR FAILED. Benchmark NOT started.
pause
exit /b 1
:fail
echo.
echo VALIDATION STOPPED.
pause
exit /b 1
