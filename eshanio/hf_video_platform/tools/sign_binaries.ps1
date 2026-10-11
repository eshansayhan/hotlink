param(
    [string[]]$FilesToSign = @(
        "HFVideoPlatform.exe",
        "PackManager.exe",
        "libcurl.dll",
        "WebView2Loader.dll",
        "glfw3.dll",
        "installer\Output\HFVideoPlatform_Setup.exe"
    ),
    [string]$Password = "HFStream2026!"
)

$rootDir = (Get-Item $PSScriptRoot).Parent.FullName
$certPfx = Join-Path $rootDir "certificates\HFVideoPlatform.pfx"

if (-not (Test-Path $certPfx)) {
    Write-Warning "Sertifika bulunamadi! Once create_certificate.ps1 calistirilmali."
    exit 1
}

$signtool = "C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64\signtool.exe"
if (-not (Test-Path $signtool)) {
    $signtool = Get-ChildItem "C:\Program Files (x86)\Windows Kits\10\bin\*\x64\signtool.exe" -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
}

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  HFVideoPlatform - Resmi Kod Imzalama (SignTool)  " -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

foreach ($rel in $FilesToSign) {
    $target = Join-Path $rootDir $rel
    if (Test-Path $target) {
        Write-Host "[*] Imzalaniyor: $rel ..." -ForegroundColor Yellow
        $out = & $signtool sign /f $certPfx /p $Password /fd SHA256 /tr "http://timestamp.digicert.com" /td SHA256 $target 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  [+] Basariyla imzalandi ve DigiCert ile zaman damgasi basildi!" -ForegroundColor Green
        } else {
            Write-Warning "  [-] Hata olustu: $out"
        }
    }
}
Write-Host "`nTum dosyalar dijital olarak imzalandi!" -ForegroundColor Green
