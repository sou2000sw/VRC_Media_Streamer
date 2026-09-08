@echo off
rem ==========================================================================
rem  app_audio_capture - build script (MSVC x64)
rem  ASCII only on purpose: .bat is read as cp932 by cmd.exe.
rem ==========================================================================
setlocal enabledelayedexpansion

set "HERE=%~dp0"
set "SRC=%HERE%src\main.cpp"
set "OUTDIR=%HERE%build"

if not exist "%SRC%" (
    echo [build] source not found: %SRC%
    echo [build] Phase P0 is not implemented yet. See docs\TASK25_*.md
    exit /b 1
)

set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "%VSWHERE%" (
    echo [build] vswhere.exe not found. Install Visual Studio with the C++ workload.
    exit /b 2
)

for /f "usebackq tokens=*" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VSPATH=%%i"
if "%VSPATH%"=="" (
    echo [build] No Visual Studio installation with the C++ toolset was found.
    exit /b 2
)

set "VCVARS=%VSPATH%\VC\Auxiliary\Build\vcvars64.bat"
if not exist "%VCVARS%" (
    echo [build] vcvars64.bat not found under: %VSPATH%
    exit /b 2
)

rem  vcvars64.bat itself may print "'vswhere.exe' is not recognized" on stderr.
rem  That message comes from Microsoft's own script, not from this one, and is harmless.
rem  Verified 2026-09-06: VSPATH is resolved correctly and the build succeeds.
call "%VCVARS%" >nul
if errorlevel 1 (
    echo [build] failed to initialize the MSVC environment.
    exit /b 2
)

if not exist "%OUTDIR%" mkdir "%OUTDIR%"

cl /nologo /std:c++17 /utf-8 /EHsc /O2 /W4 /DUNICODE /D_UNICODE ^
   /Fe:"%OUTDIR%\app_audio_capture.exe" ^
   /Fo:"%OUTDIR%\\" ^
   "%SRC%" ^
   /link ole32.lib mmdevapi.lib avrt.lib

if errorlevel 1 (
    echo [build] FAILED
    exit /b 3
)

echo [build] OK -^> %OUTDIR%\app_audio_capture.exe
endlocal
