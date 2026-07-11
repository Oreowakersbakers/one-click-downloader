param(
    [Parameter(Mandatory = $true)]
    [string]$Version
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

python scripts/verify-version.py --tag "v$Version"
python -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name "One-Click Downloader" `
    --icon "oneclickdl/assets/oneclick.ico" `
    --add-data "oneclickdl/assets;oneclickdl/assets" `
    oneclick.py

$ReleaseDir = Join-Path $Root "release"
if (Test-Path $ReleaseDir) {
    Remove-Item -Recurse -Force $ReleaseDir
}
New-Item -ItemType Directory -Path $ReleaseDir | Out-Null

$Portable = Join-Path $ReleaseDir "OneClickDownloader-$Version-Portable.exe"
Copy-Item "dist/One-Click Downloader.exe" $Portable

$ExtensionZip = Join-Path $ReleaseDir "OneClickDownloader-Extension-$Version.zip"
Compress-Archive -Path "extension/*" -DestinationPath $ExtensionZip

$Checksums = Get-ChildItem $ReleaseDir -File | ForEach-Object {
    $hash = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  $($_.Name)"
}
$Checksums | Set-Content (Join-Path $ReleaseDir "SHA256SUMS.txt") -Encoding ascii

Write-Host "Release assets prepared in $ReleaseDir"
