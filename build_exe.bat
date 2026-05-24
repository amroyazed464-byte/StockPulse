@echo off
REM ═══════════════════════════════════════════════════════════════
REM  StockPulse — Build standalone Windows executable
REM  Requires: pip install pyinstaller>=6.0
REM ═══════════════════════════════════════════════════════════════
REM
REM  Usage:
REM    build_exe.bat                        # default: v2.1.0, console
REM    build_exe.bat 2.1.0                  # custom version
REM    build_exe.bat --no-console           # hide console window
REM    build_exe.bat 2.1.0 --no-console     # version + no console
REM    build_exe.bat --icon myicon.ico      # custom icon
REM ═══════════════════════════════════════════════════════════════

setlocal enabledelayedexpansion

REM ── Defaults ────────────────────────────────────────────────────
set VERSION=2.1.0
set CONSOLE_MODE=--console
set ICON_ARG=
set ICON_FILE=

REM ── Parse arguments ────────────────────────────────────────────
:parse_args
if "%~1"=="" goto :check_deps
if /i "%~1"=="--no-console" (
    set CONSOLE_MODE=--noconsole
    shift
    goto :parse_args
)
if /i "%~1"=="--icon" (
    if exist "%~2" (
        set ICON_ARG=--icon="%~f2"
        set ICON_FILE=%~2
        shift
    ) else (
        echo [WARN] Icon file not found: "%~2" — skipping
        shift
    )
    shift
    goto :parse_args
)
REM First positional arg that looks like a version number
echo %~1 | findstr /r "^[0-9]" >nul
if %errorlevel% equ 0 (
    set VERSION=%~1
    shift
    goto :parse_args
)
shift
goto :parse_args

REM ── Check prerequisites ────────────────────────────────────────
:check_deps
echo.
echo ═══════════════════════════════════════════════════════════════
echo  StockPulse EXE Builder v%VERSION%
echo ═══════════════════════════════════════════════════════════════
echo.

REM Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found on PATH.
    exit /b 1
)

REM Check / install PyInstaller
python -c "import PyInstaller" 2>nul
if %errorlevel% neq 0 (
    echo [INFO] PyInstaller not found. Installing...
    pip install pyinstaller>=6.0
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to install PyInstaller.
        exit /b 1
    )
)

REM Check entry point exists
if not exist "stock_monitor\__main__.py" (
    echo [ERROR] Entry point not found: stock_monitor\__main__.py
    echo        Run this script from the scraping_exam project root.
    exit /b 1
)

REM ── Generate version-info file for Windows metadata ─────────────
set VERFILE=%TEMP%\stockpulse_version_info.txt
call :write_verfile

REM ── Detect scrapling editable install ───────────────────────────
set SCRAPLING_PATH_ARG=
for /f "usebackq tokens=2 delims=:" %%a in (`pip show scrapling 2^>nul ^| findstr /i "Editable.project.location"`) do set SCRAPLING_RAW=%%a
for /f "tokens=*" %%i in ("!SCRAPLING_RAW!") do set SCRAPLING_EDITABLE=%%i
if not "!SCRAPLING_EDITABLE!"=="" (
    echo [INFO] Scrapling editable install at: !SCRAPLING_EDITABLE!
    set SCRAPLING_PATH_ARG=--paths "!SCRAPLING_EDITABLE!"
)

REM ── Determine output name ──────────────────────────────────────
set OUTPUT_NAME=StockPulse-v%VERSION%

echo [INFO] Output   : %OUTPUT_NAME%.exe
echo [INFO] Mode     : %CONSOLE_MODE%
if not "%ICON_FILE%"=="" echo [INFO] Icon     : %ICON_FILE%
echo.

REM ── Clean previous build artifacts ─────────────────────────────
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
if exist "%OUTPUT_NAME%.spec" del /q "%OUTPUT_NAME%.spec"

REM ── Build ──────────────────────────────────────────────────────
pyinstaller ^
  --onefile ^
  --name "%OUTPUT_NAME%" ^
  --version-file "%VERFILE%" ^
  %SCRAPLING_PATH_ARG% ^
  --collect-data apify_fingerprint_datapoints ^
  --hidden-import yfinance ^
  --hidden-import colorama ^
  --hidden-import scrapling ^
  --hidden-import scrapling.engines ^
  --hidden-import scrapling.core ^
  --hidden-import stock_monitor.sources.eastmoney ^
  --hidden-import stock_monitor.sources.sina ^
  --hidden-import stock_monitor.sources.yahoo ^
  --hidden-import stock_monitor.exporters.csv_exporter ^
  --hidden-import stock_monitor.exporters.json_exporter ^
  --hidden-import stock_monitor.notifiers.telegram ^
  %CONSOLE_MODE% ^
  %ICON_ARG% ^
  stock_monitor\__main__.py

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Build failed!
    del "%VERFILE%" 2>nul
    exit /b 1
)

REM ── Clean up temp file ─────────────────────────────────────────
del "%VERFILE%" 2>nul

echo.
echo ═══════════════════════════════════════════════════════════════
echo  Build complete!
echo  Location : dist\%OUTPUT_NAME%.exe
echo ═══════════════════════════════════════════════════════════════
echo.
echo  Quick test:
echo    dist\%OUTPUT_NAME%.exe --version
echo    dist\%OUTPUT_NAME%.exe -s NVDA -i 2
echo.
goto :eof

REM ── Generate Windows VERSIONINFO resource ──────────────────────
:write_verfile
> "%VERFILE%" (
    echo # UTF-8
    echo VSVersionInfo(
    echo   ffi=FixedFileInfo(
    echo     filevers=(%VERSION:.=, %, 0^),
    echo     prodvers=(%VERSION:.=, %, 0^),
    echo     mask=0x3f,
    echo     flags=0x0,
    echo     OS=0x40004,
    echo     fileType=0x1,
    echo     subtype=0x0,
    echo     date=(0, 0^)
    echo   ^),
    echo   kids=[
    echo     StringFileInfo(
    echo       [
    echo         StringTable(
    echo           u'040904B0',
    echo           [
    echo             StringStruct(u'CompanyName', u'StockPulse Contributors'^),
    echo             StringStruct(u'FileDescription', u'StockPulse — Real-time Stock Quote Monitor'^),
    echo             StringStruct(u'FileVersion', u'%VERSION%'^),
    echo             StringStruct(u'InternalName', u'StockPulse'^),
    echo             StringStruct(u'LegalCopyright', u'MIT License (c) 2026 StockPulse Contributors'^),
    echo             StringStruct(u'OriginalFilename', u'StockPulse-v%VERSION%.exe'^),
    echo             StringStruct(u'ProductName', u'StockPulse'^),
    echo             StringStruct(u'ProductVersion', u'%VERSION%'^),
    echo           ]
    echo         ^),
    echo       ]
    echo     ^),
    echo     VarFileInfo([VarStruct(u'Translation', [1033, 1200]^)]^),
    echo   ]
    echo ^)
)
exit /b
