$ErrorActionPreference = "Stop"
$rootDir = (Get-Item $PSScriptRoot).Parent.FullName

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  HFVideoPlatform - MASTER BUILD & IMZALAMA SISTEMI       " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 0. Calisan surecleri kapat
Write-Host "`n[0/6] Calisan surecler sonlandiriliyor..." -ForegroundColor Yellow
Get-Process -Name "HFVideoPlatform", "PackManager" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

# 1. Frontend gomme
Write-Host "`n[1/6] Frontend HTML gomuluyor (embed_frontend)..." -ForegroundColor Yellow
$embedScript = Join-Path $rootDir "core_cpp\tools\embed_frontend.ps1"
$htmlFile = Join-Path $rootDir "frontend\index.html"
$headerFile = Join-Path $rootDir "core_cpp\src\embedded\embedded_frontend.h"
powershell -ExecutionPolicy Bypass -File $embedScript $htmlFile $headerFile | Out-Null
Write-Host "  [+] Frontend basariyla gomuldu!" -ForegroundColor Green

# 2. C++ Release Derleme
Write-Host "`n[2/6] C++ Motorlari derleniyor (Release)..." -ForegroundColor Yellow
$buildDir = Join-Path $rootDir "core_cpp\build"
cmake --build $buildDir --config Release --target HFVideoPlatform --target PackManager
if ($LASTEXITCODE -ne 0) {
    Write-Error "C++ derleme basarisiz oldu!"
    exit 1
}
Write-Host "  [+] HFVideoPlatform.exe ve PackManager.exe derlendi!" -ForegroundColor Green

# 3. Exe ve DLL'leri koke kopyala
Write-Host "`n[3/6] Dosyalar kok dizine kopyalaniyor..." -ForegroundColor Yellow
$relDir = Join-Path $buildDir "Release"
Copy-Item -Force (Join-Path $relDir "HFVideoPlatform.exe") (Join-Path $rootDir "HFVideoPlatform.exe")
Copy-Item -Force (Join-Path $relDir "PackManager.exe") (Join-Path $rootDir "PackManager.exe")
if (Test-Path (Join-Path $relDir "libcurl.dll")) {
    Copy-Item -Force (Join-Path $relDir "libcurl.dll") (Join-Path $rootDir "libcurl.dll")
}
if (Test-Path (Join-Path $relDir "WebView2Loader.dll")) {
    Copy-Item -Force (Join-Path $relDir "WebView2Loader.dll") (Join-Path $rootDir "WebView2Loader.dll")
}
if (Test-Path (Join-Path $relDir "glfw3.dll")) {
    Copy-Item -Force (Join-Path $relDir "glfw3.dll") (Join-Path $rootDir "glfw3.dll")
}
Write-Host "  [+] Tum dosyalar kopyalandi!" -ForegroundColor Green

# 4. Binary'leri Dijital Imzala
Write-Host "`n[4/6] Exe ve DLL dosyalari dijital olarak imzalaniyor..." -ForegroundColor Yellow
$signScript = Join-Path $rootDir "tools\sign_binaries.ps1"
powershell -ExecutionPolicy Bypass -File $signScript
Write-Host "  [+] Dijital imzalama ve DigiCert zaman damgasi basarili!" -ForegroundColor Green

# 5. Inno Setup Kurulum Sihirbazi Derleme & Imzalama
Write-Host "`n[5/6] Inno Setup Kurulum Sihirbazi derleniyor..." -ForegroundColor Yellow
$installerScript = Join-Path $rootDir "installer\build_installer.ps1"
powershell -ExecutionPolicy Bypass -File $installerScript
Write-Host "  [+] HFVideoPlatform_Setup.exe hazir ve imzalandi!" -ForegroundColor Green

# 6. Setup ZIP Paketini Olustur & Unblock Et
Write-Host "`n[6/6] Tam Setup ZIP paketi paketleniyor..." -ForegroundColor Yellow
$zipScript = Join-Path $rootDir "make_setup_zip.ps1"
powershell -ExecutionPolicy Bypass -File $zipScript

# SmartScreen engellemesini kaldir (Unblock-File)
Unblock-File (Join-Path $rootDir "HFVideoPlatform_Setup.exe") -ErrorAction SilentlyContinue
Unblock-File (Join-Path $rootDir "HFVideoPlatform.exe") -ErrorAction SilentlyContinue
Unblock-File (Join-Path $rootDir "PackManager.exe") -ErrorAction SilentlyContinue

Write-Host "`n==========================================================" -ForegroundColor Green
Write-Host "  TEBRIKLER! HER SEY GUNCEL VE BASARIYLA TAMAMLANDI!      " -ForegroundColor Green
Write-Host "  1. HFVideoPlatform_Setup.exe (Resmi Kurulum Sihirbazi)  " -ForegroundColor Cyan
Write-Host "  2. HFVideoPlatform_Setup.zip (Tam Bagimlilik Paketi)    " -ForegroundColor Cyan
Write-Host "  3. HFVideoPlatform.exe (Saat Yani Tray + Regedit)       " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Green
