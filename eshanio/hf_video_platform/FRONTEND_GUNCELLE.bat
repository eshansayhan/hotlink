@echo off
setlocal

set ROOT=%~dp0
set EMBED=%ROOT%core_cpp\tools\embed_frontend.ps1
set HTML=%ROOT%frontend\index.html
set HEADER=%ROOT%core_cpp\src\embedded\embedded_frontend.h
set BUILD=%ROOT%core_cpp\build
set BUILT=%ROOT%core_cpp\build\Release\HFVideoPlatform.exe
set DEST=%ROOT%HFVideoPlatform.exe

echo.
echo  =====================================================
echo   HFStream - Frontend Guncelleme
echo  =====================================================
echo.

echo  [0/3] Calisan engine kontrol ediliyor...
powershell.exe -NoProfile -Command "if (Get-Process -Name HFVideoPlatform -ErrorAction SilentlyContinue) { exit 1 }"
if errorlevel 1 (
    echo  [HATA] Guncellemeden once HFVideoPlatform uygulamasini kapatin.
    pause
    exit /b 1
)
echo  [0/3] Tamam.
echo.

echo  [1/3] HTML gomme...
powershell.exe -ExecutionPolicy Bypass -File "%EMBED%" "%HTML%" "%HEADER%"
if errorlevel 1 ( echo  [HATA] Adim 1 basarisiz! & pause & exit /b 1 )
echo  [1/3] Tamam.
echo.

echo  [2/3] C++ derleniyor...
cmake --build "%BUILD%" --config Release --target HFVideoPlatform
if errorlevel 1 ( echo  [HATA] Adim 2 basarisiz! & pause & exit /b 1 )
echo  [2/3] Tamam.
echo.

echo  [3/3] Exe kopyalaniyor...
copy /Y "%BUILT%" "%DEST%" >nul
if errorlevel 1 ( echo  [HATA] Adim 3 basarisiz! & pause & exit /b 1 )
echo  [3/3] Tamam.
echo.

echo  =====================================================
echo   GUNCELLEME BASARILI!
echo   BASLAT.bat ile baslatabilirsiniz.
echo  =====================================================
echo.
set /p X=BASLAT.bat calistirilsin mi? (E/H): 
if /i %X%==E start " %ROOT%BASLAT.bat
endlocal
