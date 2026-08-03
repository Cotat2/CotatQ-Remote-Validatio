@echo off
title CotatQ v1.2.2 Exact Aer MPS Doctor
python verify_patch_v122.py
if errorlevel 1 goto :fail
python doctor_v122.py
if errorlevel 1 goto :fail
echo.
echo Everything passed.
pause
exit /b 0
:fail
echo.
echo v1.2.2 doctor FAILED. Do not run the benchmark.
pause
exit /b 1
