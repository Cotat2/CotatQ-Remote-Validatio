@echo off
title CotatQ v1.2.1 Strict Compatibility Doctor
python verify_patch_v121.py
if errorlevel 1 goto :fail
python doctor_v121.py
if errorlevel 1 goto :fail
echo.
echo Everything passed.
pause
exit /b 0
:fail
echo.
echo Compatibility doctor FAILED. Do not run benchmark.
pause
exit /b 1
