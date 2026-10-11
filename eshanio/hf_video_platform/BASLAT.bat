@echo off
chcp 65001 > nul
cls

echo.
echo  ████████████████████████████████████████████████████████
echo  ██                                                    ██
echo  ██        HFVideoPlatform  ^|  Premium Streaming       ██
echo  ██        Node.js ^| Python ^| C++ Entegre Sistem       ██
echo  ██                                                    ██
echo  ████████████████████████████████████████████████████████
echo.
echo  [*] Baslatiliyor... Lutfen bekleyin.
echo.

:: =========================================================
:: 0. Eski calisan surecleri temizle (port catismasini onler)
:: =========================================================
echo  [*] Port catismasi varsa baska uygulamalar kapatilmayacak.
echo.

:: =========================================================
:: 1. Node.js var mi kontrol et
:: =========================================================
where node > nul 2>&1
if %errorlevel% neq 0 (
    echo  [HATA] Node.js bulunamadi! Lutfen https://nodejs.org adresinden yukleyin.
    pause
    exit /b 1
)

:: =========================================================
:: 3. start.js ile tum motorlari tek seferde baslat
:: =========================================================
echo  [*] C++ video motoru ve Node API baslatiliyor...
echo  [*] Tarayici otomatik acilacak. Acilmazsa: http://localhost:3000
echo.
echo  Durdurmak icin bu pencereyi kapatin veya CTRL+C basin.
echo  ========================================================
echo.

node "%~dp0start.js"

pause
