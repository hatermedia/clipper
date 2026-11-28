param(
    [switch]$SkipZip
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Dist = Join-Path $PSScriptRoot "desktop-dist\Clipper"
$Build = Join-Path $PSScriptRoot "desktop-build"
$SpecDir = Join-Path $Build "spec"
$Release = Join-Path $PSScriptRoot "release"
$Icon = Join-Path $PSScriptRoot "icon.ico"

if (-not (Test-Path $Python)) {
    throw "Python venv not found at $Python."
}

$Version = & $Python -c "import clipper; print(clipper.__version__)"
if (-not $Version) { throw "Could not read clipper.__version__" }
$Commit = (& git -C $Root rev-parse HEAD).Trim()
if (-not $Commit) { throw "Could not read the source commit" }
$Dirty = (& git -C $Root status --porcelain)
if ($Dirty) {
    throw "Refusing to build from a dirty working tree. Commit or stash changes first."
}

Write-Host "Building Clipper $Version native desktop from $Commit..." -ForegroundColor Cyan
Remove-Item -Recurse -Force $Dist, $Build -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $Release | Out-Null
New-Item -ItemType Directory -Force $SpecDir | Out-Null
New-Item -ItemType Directory -Force $Build | Out-Null
$VersionFile = Join-Path $env:TEMP "clipper-version-info-$PID.txt"
& $Python (Join-Path $PSScriptRoot "make_version_info.py") --version $Version --output $VersionFile
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $VersionFile)) {
    throw "Could not generate the Windows version resource"
}
Remove-Item -Force (Join-Path $PSScriptRoot "clipper.spec") -ErrorAction SilentlyContinue

$ErrorActionPreference = "Continue"
& $Python -m PyInstaller `
    --noconfirm --clean --onedir --windowed `
    --name Clipper `
    --distpath (Join-Path $PSScriptRoot "desktop-dist") `
    --workpath $Build `
    --specpath $SpecDir `
    --icon $Icon `
    --version-file $VersionFile `
    --collect-all clipper `
    --collect-all faster_whisper `
    --collect-all ctranslate2 `
    --collect-all tokenizers `
    --collect-all onnxruntime `
    --collect-all rapidocr_onnxruntime `
    --collect-all pyclipper `
    --collect-all shapely `
    --collect-all av `
    --hidden-import faster_whisper `
    --hidden-import clipper.desktop `
    --exclude-module tkinter `
    --exclude-module pytest `
    --exclude-module pip `
    (Join-Path $PSScriptRoot "clipper_desktop_entry.py")
$BuildExit = $LASTEXITCODE
$ErrorActionPreference = "Stop"
if ($BuildExit -ne 0) { throw "PyInstaller failed with exit code $BuildExit" }

$FfmpegBin = if ($env:CLIPPER_FFMPEG_DIR) { $env:CLIPPER_FFMPEG_DIR } else { Join-Path $env:USERPROFILE "tools\ffmpeg\bin" }
New-Item -ItemType Directory -Force (Join-Path $Dist "bin") | Out-Null
foreach ($exe in @("ffmpeg.exe", "ffprobe.exe")) {
    $source = Join-Path $FfmpegBin $exe
    if (-not (Test-Path $source)) { throw "Missing $source. Set CLIPPER_FFMPEG_DIR or install FFmpeg." }
    Copy-Item $source (Join-Path $Dist "bin\$exe") -Force
}

$ReadmeSource = Join-Path $PSScriptRoot "PORTABLE_DESKTOP_README.txt"
$ReadmeText = Get-Content $ReadmeSource -Raw
$ReadmeText = $ReadmeText.Replace("__CLIPPER_VERSION__", $Version)
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText(
    (Join-Path $Dist "README.txt"), $ReadmeText, $Utf8NoBom
)
Copy-Item (Join-Path $Root "LICENSE") (Join-Path $Dist "LICENSE") -Force

& $Python (Join-Path $PSScriptRoot "prepare_whisper_model.py") (Join-Path $PSScriptRoot "models\base.en")
if ($LASTEXITCODE -ne 0) { throw "Could not stage the offline Whisper model" }
& (Join-Path $PSScriptRoot "bundle_runtime.ps1") -Dist $Dist -Python $Python -Root $Root
if ($LASTEXITCODE -ne 0) { throw "Could not bundle runtime dependencies" }

& $Python (Join-Path $PSScriptRoot "sanitize_payload.py") `
    --dist $Dist `
    --version $Version `
    --commit $Commit
if ($LASTEXITCODE -ne 0) { throw "Could not sanitize the release payload" }

$SizeMb = [math]::Round((Get-ChildItem $Dist -Recurse -File | Measure-Object Length -Sum).Sum / 1MB, 1)
Write-Host "Native folder: $Dist ($SizeMb MB)" -ForegroundColor Green

if (-not $SkipZip) {
    $Zip = Join-Path $Release "clipper-$Version-windows-x64-native.zip"
    Write-Host "Compressing to $Zip ..." -ForegroundColor Cyan
    Compress-Archive -Path (Join-Path $Dist "*") -DestinationPath $Zip -CompressionLevel Optimal -Force
    $ZipMb = [math]::Round((Get-Item $Zip).Length / 1MB, 1)
    Write-Host "Zip: $Zip ($ZipMb MB)" -ForegroundColor Green
}
