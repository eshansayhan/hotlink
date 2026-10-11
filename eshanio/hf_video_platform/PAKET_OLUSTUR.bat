@echo off
chcp 65001 > nul
cls

echo.
echo  ============================================================
echo   HFVideoPlatform  — Tasinabilir Paket Olusturucu
echo   Bu script, herhangi bir bilgisayara kopyalanabilir
echo   bir dist\ klasoru olusturur.
echo  ============================================================
echo.

set ROOT=%~dp0
set DIST=%ROOT%dist
set SRC_CPP=%ROOT%core_cpp\build\Release
set SRC_FRONT=%ROOT%frontend

:: =====================================================
:: 0. Kontroller
:: =====================================================
if not exist "%SRC_CPP%\HFVideoPlatform.exe" (
    echo [HATA] HFVideoPlatform.exe bulunamadi!
    echo        Once "core_cpp\build\Release\" icinde derleme yapin.
    echo        Veya BUILD_DAGITIM.bat dosyasini calistirin.
    pause
    exit /b 1
)

:: =====================================================
:: 1. Temizlik ve klasor yapisi
:: =====================================================
echo [1/4] Klasor yapisi hazirlaniyor...
if exist "%DIST%" rmdir /S /Q "%DIST%"
mkdir "%DIST%"
mkdir "%DIST%\frontend"
echo       Tamam.

:: =====================================================
:: 2. C++ EXE + DLL'ler
:: =====================================================
echo [2/4] C++ motoru kopyalaniyor...
copy /Y "%SRC_CPP%\HFVideoPlatform.exe" "%DIST%\" > nul
copy /Y "%SRC_CPP%\libcurl.dll"         "%DIST%\" > nul 2>&1
copy /Y "%SRC_CPP%\WebView2Loader.dll"  "%DIST%\" > nul 2>&1

:: _deps altindaki libcurl.dll
if exist "%ROOT%core_cpp\build\_deps\curl-build\lib\Release\libcurl.dll" (
    copy /Y "%ROOT%core_cpp\build\_deps\curl-build\lib\Release\libcurl.dll" "%DIST%\" > nul
)
echo       Tamam.

:: =====================================================
:: 3. Frontend dosyalari
:: =====================================================
echo [3/4] Frontend kopyalaniyor...
xcopy /S /Y /Q "%SRC_FRONT%\*" "%DIST%\frontend\" > nul
echo       Tamam.

:: =====================================================
:: 4. Kullanici icin baslatici BAT
:: =====================================================
echo [4/4] Baslatici olusturuluyor...
(
echo @echo off
echo start "" "%~dp0HFVideoPlatform.exe"
) > "%DIST%\HFVideoStart.bat"
echo       Tamam.

:: =====================================================
:: Sonuc
:: =====================================================
echo.
echo  ============================================================
echo   PAKET HAZIRLANDI!
echo   Konum: %DIST%
echo.
echo   Bu "dist\" klasorunu istediginiz yere kopyalayin.
echo   Calistirmak icin: HFVideoPlatform.exe  (cift tiklayın)
echo.
echo   Masaustu video motoru Node.js gerektirmez.
echo  ============================================================
echo.
explorer "%DIST%"
pause
