param(
    [string]$Output = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $Output) {
    $Output = Join-Path $Root "packaging\release\ffmpeg-source"
}
$Files = @(
    @{
        Name = "ffmpeg-74e4393595.tar.gz"
        Url = "https://github.com/FFmpeg/FFmpeg/archive/74e4393595.tar.gz"
        Hash = "4ae3618b0d38a14bb8f86a6b90de63c4b6b55d4de8e812a4900d07d2188b54de"
    },
    @{
        Name = "x264-0480cb05.tar.gz"
        Url = "https://github.com/mirror/x264/archive/0480cb05fa188d37ae87e8f4fd8f1aea3711f7ee.tar.gz"
        Hash = "d0967a1348c85dfde363bb52610403be898171493100561efa0dd05d5fd1ae50"
    },
    @{
        Name = "x265-0aa41217.tar.gz"
        Url = "https://github.com/Multicorewareinc/x265/archive/0aa4121746654e88564d0dfa16143f60ad6eabff.tar.gz"
        Hash = "9cedb0f96543d44857e9a92a221fc8906b9cc8a335a19d7eb19d5127993c78ac"
    }
)

New-Item -ItemType Directory -Force $Output | Out-Null
foreach ($file in $Files) {
    $target = Join-Path $Output $file.Name
    if (-not (Test-Path $target)) {
        Write-Host "Downloading $($file.Name) ..."
        Invoke-WebRequest -Uri $file.Url -OutFile $target -UseBasicParsing
    }
    $hash = (Get-FileHash $target -Algorithm SHA256).Hash.ToLower()
    if ($hash -ne $file.Hash) {
        throw "Source hash mismatch for $($file.Name): expected $($file.Hash), got $hash"
    }
    Write-Host "$($file.Name)  $hash" -ForegroundColor Green
}
Write-Host "Source archives: $Output"
Write-Host "Upload this folder with the release, or provide the GPLv3 written offer."
