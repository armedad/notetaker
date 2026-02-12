@echo off
REM Notetaker Installation Script Launcher for Windows
REM This will run the PowerShell installation script

echo ============================================
echo Notetaker Installation
echo ============================================
echo.

REM Check if running as administrator
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo WARNING: Not running as Administrator.
    echo Some installations may require admin privileges.
    echo.
    echo To run as Administrator:
    echo   Right-click this file and select "Run as administrator"
    echo.
    pause
)

REM Run PowerShell installer
powershell -ExecutionPolicy Bypass -File "%~dp0install.ps1"

if %errorLevel% neq 0 (
    echo.
    echo Installation encountered errors. Please check the output above.
    pause
)
