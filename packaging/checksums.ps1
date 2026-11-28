param(
    [string]$Version = "",
    # Path to the offline Ed25519 release key (see sign_release.py). When given,
    # SHA256SUMS.txt.sig is written next to the checksums for upload.
    [string]$SigningKey = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Release = Join-Path $PSScriptRoot "release"

if (-not $Version) {
    $Version = & $Python -c "import clipper; print(clipper.__version__)"
}
if (-not $Version) { throw "Could not read Clipper version" }

$Sums = Join-Path $Release "SHA256SUMS.txt"
$Signature = "$Sums.sig"
$Lines = @()
$Artifacts = Get-ChildItem $Release -File |
    Where-Object { $_.Name -notlike "SHA256SUMS.txt*" -and $_.Name -like "*$Version*" } |
    Sort-Object Name

foreach ($File in $Artifacts) {
    $Hash = (Get-FileHash $File.FullName -Algorithm SHA256).Hash.ToLower()
    $Lines += "$Hash  $($File.Name)"
    Write-Host ("{0}  {1}" -f $Hash.Substring(0, 12), $File.Name) -ForegroundColor DarkGray
}
if (-not $Lines) { throw "No release artifacts found for $Version in $Release" }

Set-Content -Path $Sums -Value $Lines -Encoding ascii
Write-Host "Wrote $Sums ($($Lines.Count) artifacts)" -ForegroundColor Green

if ($SigningKey) {
    & $Python (Join-Path $PSScriptRoot "sign_release.py") sign $Sums --key $SigningKey
    if ($LASTEXITCODE -ne 0) { throw "Signing SHA256SUMS.txt failed" }
    Write-Host "Wrote $Signature - upload it with the release." -ForegroundColor Green
} else {
    Write-Host "No -SigningKey given: the checksums are unsigned. Installed builds with UPDATE_PUBLIC_KEYS set will refuse this release." -ForegroundColor Yellow
}
