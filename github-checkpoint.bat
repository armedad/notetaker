@echo off
setlocal EnableExtensions
REM github-checkpoint.bat - Commit and push changes in notetaker (Windows)
REM
REM Usage:
REM   github-checkpoint.bat "Your commit message here"
REM
REM Examples:
REM   github-checkpoint.bat "Fix transcription bug"
REM   github-checkpoint.bat "Add audio compression support"
REM
REM The script will:
REM   1. Show any uncommitted changes
REM   2. Stage all changes (git add -A)
REM   3. Commit with your message
REM   4. Push to remote

cd /d "%~dp0"

if "%~1"=="" (
  echo Usage: github-checkpoint.bat "Your commit message"
  echo.
  echo Examples:
  echo   github-checkpoint.bat "Fix transcription bug"
  echo   github-checkpoint.bat "Add audio compression support"
  exit /b 1
)

set "commit_msg=%*"

REM Worktrees on //cc/apps need safe.directory (see AGENTS.md).
for %%I in ("%~dp0.") do set "REPO_DIR=%%~fI"
set "REPO_SAFE=%REPO_DIR:\=/%"
set "GIT_CONFIG_COUNT=1"
set "GIT_CONFIG_KEY_0=safe.directory"
set "GIT_CONFIG_VALUE_0=%REPO_SAFE%"

REM Check if there are any changes (unstaged, staged, or untracked)
git diff --quiet
if errorlevel 1 goto :has_changes
git diff --cached --quiet
if errorlevel 1 goto :has_changes
for /f %%i in ('git ls-files --others --exclude-standard 2^>nul') do (
  goto :has_changes
)
echo No changes to commit
exit /b 0

:has_changes
echo Changes detected:
git status --short
echo.

git add -A
if errorlevel 1 exit /b %errorlevel%

echo Commit: %commit_msg%
git commit -m "%commit_msg%"
if errorlevel 1 exit /b %errorlevel%

echo.
echo Pushing...
git rev-parse --abbrev-ref --symbolic-full-name "@{u}" >nul 2>&1
if errorlevel 1 (
  git push -u origin HEAD
) else (
  git push
)
if errorlevel 1 exit /b %errorlevel%

echo.
echo Done
exit /b 0
