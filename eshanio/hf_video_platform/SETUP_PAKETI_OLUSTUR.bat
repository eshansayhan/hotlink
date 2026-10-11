@echo off
chcp 65001 > nul
cls

echo.
echo  ==============================================================
echo   HFVideoPlatform - GitHub Tam Kurulum Paketi (ZIP) Olusturucu
echo  ==============================================================
echo.

set ROOT=%~dp0
cd /D "%ROOT%"

powershell.exe -ExecutionPolicy Bypass -File "%ROOT%make_setup_zip.ps1"

if %errorlevel% neq 0 (
    echo.
    echo  [HATA] Paketleme basarisiz oldu!
    pause
    exit /b 1
)

echo.
echo  ==============================================================
echo   PAKETLEME BASARIYLA TAMAMLANDI!
echo   HFVideoPlatform_Setup.zip hazir.
echo   GitHub reponuza (hfstream) yukleyebilirsiniz:
echo   https://github.com/eshansayhan/hfstream/blob/main/HFVideoPlatform_Setup.zip
echo  ==============================================================
echo.
pause
