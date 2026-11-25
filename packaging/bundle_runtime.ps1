param(
    [Parameter(Mandatory = $true)][string]$Dist,
    [Parameter(Mandatory = $true)][string]$Python,
    [Parameter(Mandatory = $true)][string]$Root
)

$ErrorActionPreference = "Stop"

$Site = & $Python -c "import sysconfig; print(sysconfig.get_paths()['purelib'])"
if (-not $Site -or -not (Test-Path $Site)) { throw "Could not locate site-packages." }

# PyInstaller 6 puts the app's loadable DLLs in _internal. App-local runtime
# DLLs must live beside python's DLLs, not beside the launcher .exe.
$Internal = Join-Path $Dist "_internal"
if (-not (Test-Path $Internal)) { $Internal = $Dist }

# The MSVC runtime version comes from the active PySide6 toolchain. CTranslate2
# ships the exact Intel OpenMP runtime used by its native build.
$PySide = Join-Path $Site "PySide6"
$CTranslate = Join-Path $Site "ctranslate2"
$RuntimeDlls = @(
    @{ Name = "msvcp140.dll"; Source = $PySide },
    @{ Name = "msvcp140_1.dll"; Source = $PySide },
    @{ Name = "msvcp140_2.dll"; Source = $PySide },
    @{ Name = "msvcp140_codecvt_ids.dll"; Source = $PySide },
    @{ Name = "vcruntime140.dll"; Source = $PySide },
    @{ Name = "vcruntime140_1.dll"; Source = $PySide },
    @{ Name = "concrt140.dll"; Source = $PySide },
    @{ Name = "vcamp140.dll"; Source = $PySide },
    @{ Name = "vccorlib140.dll"; Source = $PySide },
    @{ Name = "vcomp140.dll"; Source = $PySide },
    @{ Name = "libiomp5md.dll"; Source = $CTranslate }
)
foreach ($dll in $RuntimeDlls) {
    $source = Join-Path $dll.Source $dll.Name
    if (-not (Test-Path $source)) {
        throw "Missing build-toolchain runtime DLL: $source"
    }
    Copy-Item $source (Join-Path $Internal $dll.Name) -Force
}
foreach ($required in @("msvcp140.dll", "vcruntime140.dll", "libiomp5md.dll")) {
    if (-not (Test-Path (Join-Path $Internal $required))) {
        throw "Runtime DLL was not bundled: $required"
    }
}

$AssetDir = Join-Path $Internal "clipper\assets"
if (-not (Test-Path $AssetDir)) {
    $AssetDir = Join-Path $Dist "clipper\assets"
}
if (-not (Test-Path $AssetDir)) {
    throw "Frozen clipper assets directory was not found under $Dist."
}

$WhisperSource = Join-Path $Root "packaging\models\base.en"
if (-not (Test-Path (Join-Path $WhisperSource "model.bin"))) {
    throw "Whisper base.en model was not staged. Run packaging/prepare_whisper_model.py first."
}
$WhisperDest = Join-Path $AssetDir "models\base.en"
New-Item -ItemType Directory -Force $WhisperDest | Out-Null
Copy-Item (Join-Path $WhisperSource "*") $WhisperDest -Recurse -Force

Copy-Item (Join-Path $Root "THIRD_PARTY_NOTICES.txt") (Join-Path $Dist "THIRD_PARTY_NOTICES.txt") -Force
Copy-Item (Join-Path $Root "packaging\FFMPEG_NOTICE.txt") (Join-Path $Dist "FFMPEG_NOTICE.txt") -Force
Copy-Item (Join-Path $Root "packaging\COPYING.GPLv3.txt") (Join-Path $Dist "COPYING.GPLv3.txt") -Force
$LicenseSource = Join-Path $Root "packaging\licenses"
if (-not (Test-Path $LicenseSource)) {
    throw "License text directory is missing: $LicenseSource"
}
Copy-Item $LicenseSource (Join-Path $Dist "licenses") -Recurse -Force
Copy-Item (Join-Path $Root "packaging\close_clipper.ps1") (Join-Path $Dist "close_clipper.ps1") -Force

Write-Host "Bundled CRT/OpenMP runtime, offline Whisper model, and notices."
