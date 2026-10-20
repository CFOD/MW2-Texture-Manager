@echo off
title MW2 Tool Builder (Icon Edition)
echo ========================================================
echo        MW2 Upscale Assistant - EXE Builder
echo ========================================================
echo.

:: Check dependencies
if not exist "iwi2dds.exe" echo [NOTE] iwi2dds.exe not found - it will not be bundled; users must place it beside the EXE.
if not exist "texconv.exe" echo [ERROR] texconv.exe missing! & pause & exit /b
if not exist "imgXiwi.exe" echo [NOTE] imgXiwi.exe not found - it will not be bundled; users must place it beside the EXE.
if not exist "libsquish.dll" echo [ERROR] libsquish.dll missing! & pause & exit /b
if not exist "upscaler\realesrgan-ncnn-vulkan.exe" echo [ERROR] upscaler\realesrgan-ncnn-vulkan.exe missing! & pause & exit /b
if not exist "upscaler\models\realesrgan-x4plus.bin" echo [ERROR] upscaler\models\realesrgan-x4plus.bin missing! & pause & exit /b

:: Check for Icon (Optional but recommended for this build)
if not exist "icon.ico" (
    echo [WARNING] icon.ico not found. Using default Python icon.
    echo To use a custom icon, place an 'icon.ico' file in this folder.
)

echo Step 1: Installing prerequisites...
pip install pyinstaller Pillow customtkinter tkinterdnd2

echo.
echo Step 2: Building All-in-One Executable...
echo.

:: The spec file (MW2_Tool.spec) is the source of truth for the build —
:: it also bundles customtkinter's theme assets and tkinterdnd2's native
:: Tcl extension via collect_data_files(), which plain CLI flags below
:: don't cover. Prefer building from the spec if it's present.
if exist "MW2_Tool.spec" (
    python -m PyInstaller MW2_Tool.spec
    goto :check_result
)

:: Fallback: construct the command by hand (used only if the .spec is missing)
set CMD=python -m PyInstaller --noconsole --onefile

:: Add Icon if it exists
if exist "icon.ico" set CMD=%CMD% --icon "icon.ico"

:: Add Data Dependencies
set CMD=%CMD% --add-data "texconv.exe;." --add-data "libsquish.dll;." --add-data "icon.ico;."
set CMD=%CMD% --collect-data customtkinter --collect-data tkinterdnd2
set CMD=%CMD% --add-data "upscaler\realesrgan-ncnn-vulkan.exe;upscaler" --add-data "upscaler\vcomp140.dll;upscaler"
set CMD=%CMD% --add-data "upscaler\models\realesrgan-x4plus.bin;upscaler\models" --add-data "upscaler\models\realesrgan-x4plus.param;upscaler\models"

:: Finalize command with script name
set CMD=%CMD% --name "MW2_Tool" mw2_upscale_assistant.py

:: Execute
%CMD%

:check_result

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