@echo off
chcp 65001 > nul
cls

set ROOT=%~dp0
cd /D "%ROOT%"

powershell.exe -ExecutionPolicy Bypass -File "%ROOT%tools\build_all.ps1"

if %errorlevel% neq 0 (
    echo.
    echo  [HATA] Islem sirasinda bir hata olustu!
    pause
    exit /b 1
)

echo.
pause
