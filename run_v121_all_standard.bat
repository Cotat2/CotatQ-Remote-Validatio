@echo off
title CotatQ v1.2.1 Complete STANDARD
python verify_patch_v121.py
if errorlevel 1 goto :fail
python doctor_v121.py
if errorlevel 1 goto :fail
python independent_validation_v121.py --suite reproduction --mode standard --runner-label local-or-external
if errorlevel 1 goto :fail
python independent_validation_v121.py --suite strong --mode standard --runner-label local-or-external
if errorlevel 1 goto :fail
python bundle_results_v121.py
pause
exit /b 0
:fail
echo Validation failed or was blocked.
pause
exit /b 1
