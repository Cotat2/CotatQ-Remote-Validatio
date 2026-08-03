@echo off
title CotatQ v1.2.2 Strong Rival FULL
echo Run ONLY after v1.2.2 Strong STANDARD is inspected.
python verify_patch_v122.py
if errorlevel 1 goto :fail
python doctor_v122.py
if errorlevel 1 goto :fail
python independent_validation_v122.py --suite strong --mode full --runner-label local-or-external
pause
exit /b 0
:fail
echo FULL blocked.
pause
exit /b 1
