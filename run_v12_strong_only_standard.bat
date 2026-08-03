@echo off
title CotatQ v1.2 Strong Rival Standard
python verify_freeze_v12.py
if errorlevel 1 goto :fail
python doctor_v12.py
python independent_validation_v12.py --suite strong --mode standard --runner-label local-or-external
python bundle_results_v12.py
pause
exit /b 0
:fail
pause
exit /b 1
