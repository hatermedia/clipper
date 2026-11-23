@echo off
title Clipper
cd /d "%~dp0"
"%~dp0clipper.exe" ui
echo.
echo Clipper stopped. Press any key to close this window.
pause >nul
