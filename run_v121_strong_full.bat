@echo off
title CotatQ v1.2.1 Strong Rival FULL
echo ============================================================
echo CotatQ v1.2.1 - STRONG RIVAL FULL
echo Run ONLY after the compatibility-fixed STANDARD is inspected.
echo SAME locked 90 strong-rival cases.
echo ============================================================
python verify_patch_v121.py
if errorlevel 1 goto :fail

python doctor_v121.py
if errorlevel 1 goto :doctor_fail

python independent_validation_v121.py --suite strong --mode full --runner-label local-or-external
if errorlevel 1 goto :fail

python bundle_results_v121.py
pause
exit /b 0

:doctor_fail
echo STRICT DOCTOR FAILED. FULL NOT STARTED.
pause
exit /b 1

:fail
echo VALIDATION STOPPED.
pause
exit /b 1
