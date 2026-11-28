param(
    [string]$Version = "",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$AppDir = Join-Path $PSScriptRoot "desktop-dist\Clipper"
$Release = Join-Path $PSScriptRoot "release"
$Makensis = Join-Path $env:USERPROFILE "tools\nsis\nsis-3.11\makensis.exe"

if (-not $Version) {
    $Version = & $Python -c "import clipper; print(clipper.__version__)"
}
if (-not $Version) { throw "Could not read Clipper version" }
$Commit = (& git -C $Root rev-parse HEAD).Trim()
if (-not $Commit) { throw "Could not read the source commit" }
$Dirty = (& git -C $Root status --porcelain)
if ($Dirty) {
    throw "Refusing to package from a dirty working tree. Commit or stash changes first."
}
$Parts = $Version.Split(".")
while ($Parts.Count -lt 3) { $Parts += "0" }
$ViVersion = "$($Parts[0]).$($Parts[1]).$($Parts[2]).0"

if (-not $SkipBuild) {
    & (Join-Path $PSScriptRoot "build_desktop.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Desktop build failed" }
}

if (-not (Test-Path (Join-Path $AppDir "Clipper.exe"))) {
    throw "Clipper.exe not found in $AppDir. Run packaging\build_desktop.ps1 first."
}
$RequiredFiles = @(
    "Clipper.exe",
    "README.txt",
    "BUILD_INFO.txt",
    "close_clipper.ps1",
    "THIRD_PARTY_NOTICES.txt",
    "FFMPEG_NOTICE.txt",
    "COPYING.GPLv3.txt",
    "licenses\Apache-2.0.txt",
    "licenses\MPL-2.0.txt",
    "bin\ffmpeg.exe",
    "bin\ffprobe.exe",
    "_internal\clipper\assets\models\base.en\model.bin"
)
foreach ($relative in $RequiredFiles) {
    if (-not (Test-Path (Join-Path $AppDir $relative))) {
        throw "Release payload is missing $relative. Rebuild with packaging\build_desktop.ps1."
    }
}
& $Python (Join-Path $PSScriptRoot "sanitize_payload.py") `
    --dist $AppDir `
    --version $Version `
    --commit $Commit `
    --check
if ($LASTEXITCODE -ne 0) {
    throw "Release payload failed the packaging integrity check. Rebuild with packaging\build_desktop.ps1."
}
$ExeInfo = (Get-Item (Join-Path $AppDir "Clipper.exe")).VersionInfo
if ($ExeInfo.FileVersion -ne $Version -or $ExeInfo.ProductVersion -ne $Version) {
    throw "Clipper.exe version resource does not match $Version. Rebuild the desktop payload."
}
if ($ExeInfo.ProductName -ne "Clipper" -or $ExeInfo.CompanyName -ne "hatermedia") {
    throw "Clipper.exe product metadata is incorrect. Rebuild the desktop payload."
}
$ReadmePath = Join-Path $AppDir "README.txt"
$ReadmeText = Get-Content $ReadmePath -Raw
if (-not $ReadmeText.Contains("Clipper $Version - Windows x64")) {
    throw "README.txt does not contain the build version $Version. Rebuild the desktop payload."
}
if ($ReadmeText.Contains("__CLIPPER_VERSION__")) {
    throw "README.txt still contains the version placeholder. Rebuild the desktop payload."
}
if (-not (Test-Path $Makensis)) {
    throw "NSIS not found at $Makensis"
}

New-Item -ItemType Directory -Force $Release | Out-Null
Set-Location $PSScriptRoot
Write-Host "Building ClipperSetup-$Version.exe ..." -ForegroundColor Cyan
& $Makensis /V2 "/DVERSION=$Version" "/DVI_VERSION=$ViVersion" "clipper.nsi"
if ($LASTEXITCODE -ne 0) { throw "makensis failed with exit code $LASTEXITCODE" }

$Setup = Join-Path $Release "ClipperSetup-$Version.exe"
if (-not (Test-Path $Setup)) { throw "Installer not found: $Setup" }

# Keep SHA256SUMS.txt in sync so the in-app updater and portable users can
# verify downloads.
$Artifacts = @($Setup)
$Portable = Join-Path $Release "clipper-$Version-windows-x64-native.zip"
if (Test-Path $Portable) { $Artifacts += $Portable }
$Dist = Join-Path $Root "dist"
foreach ($name in @(
    "clipper_gg-$Version-py3-none-any.whl",
    "clipper_gg-$Version.tar.gz"
)) {
    $artifact = Join-Path $Dist $name
    if (Test-Path $artifact) { $Artifacts += $artifact }
}
$Sums = Join-Path $Release "SHA256SUMS.txt"
$Names = @($Artifacts | ForEach-Object { Split-Path $_ -Leaf })
$Lines = @()
if (Test-Path $Sums) {
    $Lines = @(Get-Content $Sums | Where-Object {
        if (-not $_) { return $false }
        # Drop installer/zip/wheel lines from older versions so the checksum
        # file only describes the release being staged.
        if ($_ -match '\s+(ClipperSetup-.*\.exe|clipper-.*-windows-x64-native\.zip|clipper_gg-.*\.(whl|tar\.gz))$') {
            return $false
        }
        foreach ($name in $Names) {
            if ($_ -match ("\s+" + [regex]::Escape($name) + "$")) { return $false }
        }
        return $true
    })
}
foreach ($artifact in $Artifacts) {
    $Hash = (Get-FileHash $artifact -Algorithm SHA256).Hash.ToLower()
    $Name = Split-Path $artifact -Leaf
    $Lines += "$Hash  $Name"
    Write-Host "SHA-256: $Hash  $Name" -ForegroundColor DarkGray
}
Set-Content -Path $Sums -Value $Lines -Encoding ascii
$VersionedSums = Join-Path $Release "SHA256SUMS-$Version.txt"
Set-Content -Path $VersionedSums -Value $Lines -Encoding ascii
Write-Host ("Installer: {0} ({1:N1} MB)" -f $Setup, ((Get-Item $Setup).Length / 1MB)) -ForegroundColor Green
Write-Host "Checksums: $VersionedSums" -ForegroundColor Green
