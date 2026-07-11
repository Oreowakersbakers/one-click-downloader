@echo off
rem Builds a standalone "One-Click Downloader.exe" (no Python needed to RUN it).
rem
rem Double-click this file. It needs Python installed to BUILD (one time);
rem the exe it produces runs on any Windows machine on its own.
rem
rem Output: dist\One-Click Downloader.exe  — move it anywhere you like.

setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found. Install it from https://python.org ^(tick "Add to PATH"^).
    pause
    exit /b 1
)

echo Installing the pinned build toolchain...
python -m pip install --quiet -r requirements-build.txt
if errorlevel 1 goto :fail

python scripts\verify-version.py
if errorlevel 1 goto :fail

echo Building One-Click Downloader.exe ...
python -m PyInstaller ^
    --noconfirm --clean --onefile --windowed ^
    --name "One-Click Downloader" ^
    --icon "oneclickdl\assets\oneclick.ico" ^
    --add-data "oneclickdl\assets;oneclickdl\assets" ^
    oneclick.py
if errorlevel 1 goto :fail

echo.
echo Done! Your app is here:
echo     %~dp0dist\One-Click Downloader.exe
echo.
echo Move it wherever you like (Desktop is fine) and double-click to run.
pause
exit /b 0

:fail
echo.
echo Build failed — see the messages above.
pause
exit /b 1
