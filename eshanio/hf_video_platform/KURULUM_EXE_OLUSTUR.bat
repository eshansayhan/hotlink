@echo off
chcp 65001 > nul
cls

echo.
echo  ==============================================================
echo   HFVideoPlatform - Resmi Windows Kurulum Sihirbazi (Setup.exe)
echo  ==============================================================
echo.

set ROOT=%~dp0
cd /D "%ROOT%"

powershell.exe -ExecutionPolicy Bypass -File "%ROOT%installer\build_installer.ps1"

if %errorlevel% neq 0 (
    echo.
    echo  [HATA] Kurulum paketi olusturulamadi!
    pause
    exit /b 1
)

echo.
echo  ==============================================================
echo   KURULUM EXE BASARIYLA OLUSTURULDU VE IMZALANDI!
echo   Dosya: %ROOT%HFVideoPlatform_Setup.exe
echo   Kullanicilar diledigi klasore kurup kaldirabilir.
echo  ==============================================================
echo.
pause
