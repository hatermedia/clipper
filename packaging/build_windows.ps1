param(
    [switch]$SkipZip
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Dist = Join-Path $PSScriptRoot "dist\clipper"
$Build = Join-Path $PSScriptRoot "build"
$Release = Join-Path $PSScriptRoot "release"
$Icon = Join-Path $PSScriptRoot "icon.ico"

if (-not (Test-Path $Python)) {
    throw "Python venv not found at $Python. Create it and install the package first."
}

$Version = & $Python -c "import clipper; print(clipper.__version__)"
if (-not $Version) { throw "Could not read clipper.__version__" }

Write-Host "Building Clipper $Version portable..." -ForegroundColor Cyan
Remove-Item -Recurse -Force $Dist, $Build, $Release -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $Release | Out-Null

& $Python -m PyInstaller `
    --noconfirm --clean --onedir --console `
    --name clipper `
    --distpath (Join-Path $PSScriptRoot "dist") `
    --workpath $Build `
    --specpath $PSScriptRoot `
    --icon $Icon `
    --collect-all clipper `
    --collect-submodules uvicorn `
    --hidden-import clipper.web.app `
    --hidden-import uvicorn.logging `
    --hidden-import uvicorn.loops.auto `
    --hidden-import uvicorn.protocols.http.auto `
    --hidden-import uvicorn.protocols.websockets.auto `
    --hidden-import uvicorn.lifespan.on `
    --exclude-module tkinter `
    --exclude-module pytest `
    --exclude-module pip `
    (Join-Path $PSScriptRoot "clipper_entry.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

$FfmpegBin = if ($env:CLIPPER_FFMPEG_DIR) { $env:CLIPPER_FFMPEG_DIR } else { Join-Path $env:USERPROFILE "tools\ffmpeg\bin" }
foreach ($exe in @("ffmpeg.exe", "ffprobe.exe")) {
    $source = Join-Path $FfmpegBin $exe
    if (-not (Test-Path $source)) { throw "Missing $source. Set CLIPPER_FFMPEG_DIR or install FFmpeg." }
    New-Item -ItemType Directory -Force (Join-Path $Dist "bin") | Out-Null
    Copy-Item $source (Join-Path $Dist "bin\$exe") -Force
}

Copy-Item (Join-Path $PSScriptRoot "launcher-ui.cmd") (Join-Path $Dist "Clipper UI.cmd") -Force
Copy-Item (Join-Path $PSScriptRoot "launcher-cli.cmd") (Join-Path $Dist "Clipper CLI.cmd") -Force
Copy-Item (Join-Path $PSScriptRoot "PORTABLE_README.txt") (Join-Path $Dist "README.txt") -Force
Copy-Item (Join-Path $Root "LICENSE") (Join-Path $Dist "LICENSE") -Force

$SizeMb = [math]::Round((Get-ChildItem $Dist -Recurse -File | Measure-Object Length -Sum).Sum / 1MB, 1)
Write-Host "Portable folder: $Dist ($SizeMb MB)" -ForegroundColor Green

if (-not $SkipZip) {
    $Zip = Join-Path $Release "clipper-$Version-windows-x64-portable.zip"
    Write-Host "Compressing to $Zip ..." -ForegroundColor Cyan
    Compress-Archive -Path (Join-Path $Dist "*") -DestinationPath $Zip -CompressionLevel Optimal -Force
    $ZipMb = [math]::Round((Get-Item $Zip).Length / 1MB, 1)
    Write-Host "Zip: $Zip ($ZipMb MB)" -ForegroundColor Green
}
