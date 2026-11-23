param(
    [string]$Version = ""
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
$Lines = @()
$Artifacts = Get-ChildItem $Release -File |
    Where-Object { $_.Name -ne "SHA256SUMS.txt" -and $_.Name -like "*$Version*" } |
    Sort-Object Name

foreach ($File in $Artifacts) {
    $Hash = (Get-FileHash $File.FullName -Algorithm SHA256).Hash.ToLower()
    $Lines += "$Hash  $($File.Name)"
    Write-Host ("{0}  {1}" -f $Hash.Substring(0, 12), $File.Name) -ForegroundColor DarkGray
}
if (-not $Lines) { throw "No release artifacts found for $Version in $Release" }

Set-Content -Path $Sums -Value $Lines -Encoding ascii
Write-Host "Wrote $Sums ($($Lines.Count) artifacts)" -ForegroundColor Green
