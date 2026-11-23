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

# Keep SHA256SUMS.txt in sync so the in-app updater can verify downloads.
$Sums = Join-Path $Release "SHA256SUMS.txt"
$Hash = (Get-FileHash $Setup -Algorithm SHA256).Hash.ToLower()
$Name = Split-Path $Setup -Leaf
$Lines = @()
if (Test-Path $Sums) {
    $Lines = @(Get-Content $Sums | Where-Object {
        $_ -and ($_ -notmatch ("\s+" + [regex]::Escape($Name) + "$"))
    })
}
$Lines += "$Hash  $Name"
Set-Content -Path $Sums -Value $Lines -Encoding ascii
Write-Host "SHA-256: $Hash" -ForegroundColor DarkGray
Write-Host ("Installer: {0} ({1:N1} MB)" -f $Setup, ((Get-Item $Setup).Length / 1MB)) -ForegroundColor Green
