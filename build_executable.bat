@echo off
title MW2 Tool Builder (Icon Edition)
echo ========================================================
echo        MW2 Upscale Assistant - EXE Builder
echo ========================================================
echo.

:: Check dependencies
if not exist "iwi2dds.exe" echo [ERROR] iwi2dds.exe missing! & pause & exit /b
if not exist "texconv.exe" echo [ERROR] texconv.exe missing! & pause & exit /b
if not exist "imgXiwi.exe" echo [ERROR] imgXiwi.exe missing! & pause & exit /b
if not exist "libsquish.dll" echo [ERROR] libsquish.dll missing! & pause & exit /b

:: Check for Icon (Optional but recommended for this build)
if not exist "icon.ico" (
    echo [WARNING] icon.ico not found. Using default Python icon.
    echo To use a custom icon, place an 'icon.ico' file in this folder.
)

echo Step 1: Installing prerequisites...
pip install pyinstaller Pillow

echo.
echo Step 2: Building All-in-One Executable...
echo.

:: Construct command
:: We build the base command string first
set CMD=python -m PyInstaller --noconsole --onefile

:: Add Icon if it exists
if exist "icon.ico" set CMD=%CMD% --icon "icon.ico"

:: Add Data Dependencies
set CMD=%CMD% --add-data "iwi2dds.exe;." --add-data "texconv.exe;." --add-data "imgXiwi.exe;." --add-data "libsquish.dll;." --add-data "icon.ico;."

:: Add Upscaler if present (Optional)
if exist "upscaler.exe" set CMD=%CMD% --add-data "upscaler.exe;."

:: Finalize command with script name
set CMD=%CMD% --name "MW2_Tool" mw2_upscale_assistant.py

:: Execute
%CMD%

if %errorlevel% neq 0 (
    echo [ERROR] Build failed.
    pause
    exit /b
)

echo.
echo ========================================================
echo                  BUILD SUCCESSFUL!
echo ========================================================
pause