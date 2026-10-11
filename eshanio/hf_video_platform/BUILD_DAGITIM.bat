@echo off
chcp 65001 > nul
cls

echo.
echo  ████████████████████████████████████████████████████████
echo  ██   HFVideoPlatform  —  DAGITIM BUILD SISTEMI        ██
echo  ██   C++ ^| Python  ^|  Masaustu .EXE Paketi          ██
echo  ████████████████████████████████████████████████████████
echo.

set ROOT=%~dp0
set DIST=%ROOT%dist
set RUNTIME=%DIST%\runtime

:: =====================================================
:: 0. Temizlik
:: =====================================================
echo [1/4] Eski dist klasoru temizleniyor...
if exist "%DIST%" rmdir /S /Q "%DIST%"
mkdir "%DIST%"
mkdir "%RUNTIME%\python"
echo      Temiz.

:: =====================================================
:: 1. C++ Build
:: =====================================================
echo.
echo [2/4] C++ Engine derleniyor...
cd /D "%ROOT%core_cpp"
if not exist build mkdir build
cd build
cmake .. -G "Visual Studio 17 2022" -A x64 -DCMAKE_BUILD_TYPE=Release > nul 2>&1
cmake --build . --config Release
if %errorlevel% neq 0 (
    echo [HATA] C++ derleme basarisiz!
    pause
    exit /b 1
)
echo      C++ derleme tamamlandi.

:: HFVideoPlatform.exe + DLL'leri dist'e kopyala
copy /Y "%ROOT%core_cpp\build\Release\HFVideoPlatform.exe" "%DIST%\" > nul
copy /Y "%ROOT%core_cpp\build\Release\*.dll"               "%DIST%\" > nul 2>&1

:: =====================================================
:: 2. Python AI → PyInstaller ile bundled exe
:: =====================================================
echo.
echo [3/4] Python AI motoru paketleniyor (PyInstaller)...
cd /D "%ROOT%ai_python\src"

python -m pip install pyinstaller > nul 2>&1
python -m PyInstaller --onefile --distpath "%RUNTIME%\python" --name python_ai main.py

if %errorlevel% neq 0 (
    echo [UYARI] PyInstaller basarisiz. Python AI motoru dagitimda olmayacak.
) else (
    echo      Python AI motoru paketlendi.
)

:: =====================================================
:: 3. Frontend dosyalarını kopyala
:: =====================================================
echo.
echo [4/4] Frontend dosyalari kopyalaniyor...
xcopy /S /Y "%ROOT%frontend\*" "%DIST%\frontend\" > nul
echo      Frontend kopyalandi.

:: =====================================================
:: 4. Sonuc
:: =====================================================
echo.
echo  ████████████████████████████████████████████████████████
echo  ██  BUILD TAMAMLANDI!                                  ██
echo  ██  Dagitim klasoru: %DIST%
echo  ██  Kullanicilara sadece "dist\" klasorunu verin.      ██
echo  ██  HFVideoPlatform.exe'ye cift tiklasinlar, hepsi     ██
echo  ██  otomatik baslar!                                   ██
echo  ████████████████████████████████████████████████████████
echo.
explorer "%DIST%"
pause
