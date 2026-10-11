$ErrorActionPreference = "Stop"
$rootDir = (Get-Item $PSScriptRoot).Parent.FullName
$issFile = Join-Path $PSScriptRoot "setup.iss"
$outputDir = Join-Path $PSScriptRoot "Output"

# Inno Setup Derleyicisini (ISCC.exe) bul
$isccPaths = @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)

$iscc = $null
foreach ($p in $isccPaths) {
    if (Test-Path $p) {
        $iscc = $p
        break
    }
}

if (-not $iscc) {
    $found = Get-Command "iscc.exe" -ErrorAction SilentlyContinue
    if ($found) { $iscc = $found.Source }
}

if (-not $iscc) {
    Write-Error "Inno Setup Compiler (ISCC.exe) bulunamadi! Lutfen Inno Setup 6 kurun."
    exit 1
}

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  HFVideoPlatform - Kurulum Sihirbazi Derleniyor  " -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "[*] ISCC: $iscc" -ForegroundColor Yellow

# Inno Setup calistir
& $iscc $issFile
if ($LASTEXITCODE -ne 0) {
    Write-Error "Inno Setup derleme hatasi!"
    exit 1
}

$setupExe = Join-Path $outputDir "HFVideoPlatform_Setup.exe"
if (Test-Path $setupExe) {
    Write-Host "[+] Kurulum paketi olusturuldu: $setupExe" -ForegroundColor Green
    
    # Setup'i da Dijital Olarak Imzala!
    Write-Host "[*] Setup.exe dijital olarak imzalaniyor..." -ForegroundColor Yellow
    $signScript = Join-Path $rootDir "tools\sign_binaries.ps1"
    powershell -ExecutionPolicy Bypass -File $signScript -FilesToSign @("installer\Output\HFVideoPlatform_Setup.exe")
    
    # Root dizine de kopyala
    Copy-Item -Force $setupExe (Join-Path $rootDir "HFVideoPlatform_Setup.exe")
    Write-Host "[+] Root dizine kopyalandi: HFVideoPlatform_Setup.exe" -ForegroundColor Green
} else {
    Write-Error "HFVideoPlatform_Setup.exe bulunamadi!"
}
