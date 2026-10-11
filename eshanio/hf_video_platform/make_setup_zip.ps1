param(
    [string]$OutputDir = $PSScriptRoot
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.IO.Compression.FileSystem

$zipPath = Join-Path $OutputDir "HFVideoPlatform_Setup.zip"
if (Test-Path $zipPath) {
    Remove-Item -Force $zipPath
}

$tempDir = Join-Path $env:TEMP ("hf_setup_" + [System.Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

$filesToInclude = @(
    "HFVideoPlatform.exe",
    "libcurl.dll",
    "WebView2Loader.dll",
    "glfw3.dll",
    "hf_accounts.json",
    "imgui.ini",
    "master_index.json",
    "BASLAT.bat"
)

foreach ($f in $filesToInclude) {
    $src = Join-Path $OutputDir $f
    if (-not (Test-Path $src)) {
        # Check Release folder fallback
        $relSrc = Join-Path $OutputDir ("core_cpp\build\Release\" + $f)
        if (Test-Path $relSrc) {
            Copy-Item -Force $relSrc $src
        }
    }
    if (Test-Path $src) {
        Copy-Item -Force $src (Join-Path $tempDir $f)
        Write-Host "  [+] Paketlendi: $f"
    } else {
        Write-Warning "  [-] Dosya bulunamadi: $f"
    }
}

[System.IO.Compression.ZipFile]::CreateFromDirectory($tempDir, $zipPath)
Remove-Item -Recurse -Force $tempDir

$fi = Get-Item $zipPath
Write-Host "Basarili! Setup ZIP olusturuldu: $($fi.FullName) ($($fi.Length) bytes)"
