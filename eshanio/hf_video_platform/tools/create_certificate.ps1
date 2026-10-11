param(
    [string]$CertName = "HFVideoPlatform (Eshan Sayhan)",
    [string]$Password = "HFStream2026!"
)

$ErrorActionPreference = "Stop"
$rootDir = (Get-Item $PSScriptRoot).Parent.FullName
$certDir = Join-Path $rootDir "certificates"
if (-not (Test-Path $certDir)) {
    New-Item -ItemType Directory -Path $certDir -Force | Out-Null
}

$cerPath = Join-Path $certDir "HFVideoPlatform.cer"
$pfxPath = Join-Path $certDir "HFVideoPlatform.pfx"

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  HFVideoPlatform - Kod Imzalama Sertifikasi      " -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# 1. Mevcut sertifikayi kontrol et
$existing = Get-ChildItem -Path Cert:\CurrentUser\My -CodeSigningCert | Where-Object { $_.Subject -like "*$CertName*" } | Select-Object -First 1

if ($existing) {
    Write-Host "[*] Mevcut sertifika bulundu: $($existing.Thumbprint)" -ForegroundColor Green
    $cert = $existing
} else {
    Write-Host "[*] Yeni Kod Imzalama Sertifikasi olusturuluyor: $CertName" -ForegroundColor Yellow
    $cert = New-SelfSignedCertificate `
        -Type CodeSigningCert `
        -Subject "CN=$CertName, O=HFStream Network, C=TR" `
        -CertStoreLocation "Cert:\CurrentUser\My" `
        -KeySpec Signature `
        -KeyLength 2048 `
        -KeyExportPolicy Exportable `
        -NotAfter (Get-Date).AddYears(5) `
        -FriendlyName "HFVideoPlatform Official Publisher Certificate"
    
    Write-Host "[+] Sertifika basariyla olusturuldu: $($cert.Thumbprint)" -ForegroundColor Green
}

# 2. CER ve PFX olarak disari aktar
$securePass = ConvertTo-SecureString -String $Password -Force -AsPlainText
Export-Certificate -Cert $cert -FilePath $cerPath -Force | Out-Null
Export-PfxCertificate -Cert $cert -FilePath $pfxPath -Password $securePass -Force | Out-Null

Write-Host "[+] PFX Aktarildi: $pfxPath" -ForegroundColor Green
Write-Host "[+] CER Aktarildi: $cerPath" -ForegroundColor Green

# 3. Guvenilir Kok Yetkililerine (Trusted Root) Ekle
try {
    $rootStore = New-Object System.Security.Cryptography.X509Certificates.X509Store("Root", "CurrentUser")
    $rootStore.Open("ReadWrite")
    $rootStore.Add($cert)
    $rootStore.Close()
    Write-Host "[+] Sertifika Guvenilir Kok Sertifikalarina (Trusted Root) eklendi! (SmartScreen & Defender artik bu imzaya guvenir)" -ForegroundColor Cyan
} catch {
    Write-Warning "[!] Trusted Root eklenirken: $_"
}

Write-Host "`nTamamlandi! Sertifika sifresi: $Password" -ForegroundColor Green
