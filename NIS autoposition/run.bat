@echo off
setlocal enabledelayedexpansion
rem ===========================================================================
rem  ND Generator UI 실행 스크립트
rem
rem  1순위: 폴더 안에 동봉된 python\python.exe (설치 불필요, 폴더째 옮겨도 동작)
rem  2순위: 동봉 런타임이 없을 때만 Anaconda 등 시스템 conda 환경으로 대체 실행
rem
rem  사용법:
rem    run.bat              더블클릭 또는 cmd/PowerShell에서 실행
rem    run.bat --옵션       추가 인자는 그대로 파이썬 스크립트에 전달됨
rem
rem  동봉 런타임을 무시하고 conda 로 강제 실행:
rem    set ND_USE_SYSTEM_PYTHON=1
rem
rem  주의: 폴더 경로나 PATH에 괄호가 들어갈 수 있으므로
rem        ( ... ) 블록 안에서는 반드시 !VAR! (지연 확장)를 쓸 것.
rem ===========================================================================

rem 스크립트가 놓인 폴더를 작업 디렉터리로 (더블클릭 대비)
cd /d "%~dp0"

set "TARGET=nd_generator_ui.py"
set "EMBEDDED=%~dp0python\python.exe"
set "PYTHON="

if not exist "%TARGET%" (
    echo [ERROR] 실행 대상 파일이 없습니다: !CD!\%TARGET%
    goto :fail
)

rem --- 1순위: 동봉 런타임 -----------------------------------------------------
if "%ND_USE_SYSTEM_PYTHON%"=="1" goto :use_conda
if not exist "%EMBEDDED%" goto :use_conda

set "PYTHON=%EMBEDDED%"
set "RUNTIME=동봉 런타임 (python\)"
goto :run

rem --- 2순위: 시스템 conda ----------------------------------------------------
:use_conda
if "%CONDA_ENV%"=="" set "CONDA_ENV=base"
if not "%CONDA_ROOT%"=="" goto :root_ready

if "%CONDA_EXE%"=="" goto :try_path
for %%I in ("%CONDA_EXE%") do set "CONDA_ROOT=%%~dpI.."
goto :root_ready

:try_path
for /f "delims=" %%I in ('where conda.exe 2^>nul') do (
    for %%J in ("%%~dpI..") do set "CONDA_ROOT=%%~fJ"
    goto :root_ready
)

for %%D in (
    "%USERPROFILE%\anaconda3"
    "%USERPROFILE%\Anaconda3"
    "%USERPROFILE%\miniconda3"
    "%USERPROFILE%\miniforge3"
    "%LOCALAPPDATA%\Continuum\anaconda3"
    "C:\ProgramData\Anaconda3"
    "C:\ProgramData\miniconda3"
) do (
    if exist "%%~D\python.exe" (
        set "CONDA_ROOT=%%~D"
        goto :root_ready
    )
)

echo [ERROR] 동봉 런타임(python\python.exe)도, Anaconda 도 찾지 못했습니다.
echo         python 폴더가 지워졌다면 프로젝트를 다시 받거나
echo         CONDA_ROOT 환경변수로 conda 위치를 지정하세요.
goto :fail

:root_ready
for %%I in ("%CONDA_ROOT%") do set "CONDA_ROOT=%%~fI"
if /i "%CONDA_ENV%"=="base" (
    set "ENV_PREFIX=!CONDA_ROOT!"
) else (
    set "ENV_PREFIX=!CONDA_ROOT!\envs\!CONDA_ENV!"
)
if not exist "!ENV_PREFIX!\python.exe" (
    echo [ERROR] '!CONDA_ENV!' 환경의 python을 찾지 못했습니다: !ENV_PREFIX!
    goto :fail
)
if exist "!CONDA_ROOT!\Scripts\activate.bat" (
    call "!CONDA_ROOT!\Scripts\activate.bat" "!CONDA_ENV!"
) else (
    set "PATH=!ENV_PREFIX!;!ENV_PREFIX!\Library\bin;!ENV_PREFIX!\Library\usr\bin;!ENV_PREFIX!\Library\mingw-w64\bin;!ENV_PREFIX!\Scripts;!PATH!"
)
set "PYTHON=!ENV_PREFIX!\python.exe"
set "RUNTIME=conda !CONDA_ENV! (!CONDA_ROOT!)"

rem --- 실행 -------------------------------------------------------------------
:run
echo [INFO] runtime : !RUNTIME!
echo [INFO] python  : !PYTHON!
echo [INFO] run     : %TARGET%
echo.

"%PYTHON%" "%TARGET%" %*
set "EXITCODE=%ERRORLEVEL%"

if not "%EXITCODE%"=="0" (
    echo.
    echo [ERROR] 프로그램이 오류로 종료되었습니다. ^(exit code !EXITCODE!^)
    goto :fail
)

endlocal & exit /b 0

:fail
echo.
pause
endlocal & exit /b 1
