@echo off
title Clipper CLI
cd /d "%~dp0"
"%~dp0clipper.exe" %*
echo.
echo Press any key to close this window.
pause >nul
