@echo off
title Notetaker
cd /d "%~dp0"

set "PS_DEBUG="
set "PS_HELP="
:parse
if "%~1"=="" goto parsed
if /i "%~1"=="-debug" (set "PS_DEBUG=-Debug" & shift & goto parse)
if /i "%~1"=="--debug" (set "PS_DEBUG=-Debug" & shift & goto parse)
if /i "%~1"=="-help" goto help
if /i "%~1"=="--help" goto help
if /i "%~1"=="-h" goto help
echo error: unknown option: %~1 ^(try notetaker.bat -help^) >&2
exit /b 1

:help
powershell -ExecutionPolicy Bypass -File "%~dp0notetaker.ps1" -Help
exit /b %ERRORLEVEL%

:parsed
powershell -ExecutionPolicy Bypass -File "%~dp0notetaker.ps1" %PS_DEBUG%
exit /b %ERRORLEVEL%
