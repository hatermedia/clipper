# Closes Clipper before an upgrade/uninstall. Used by the NSIS installer.
$ErrorActionPreference = 'SilentlyContinue'

$installExe = Join-Path $PSScriptRoot 'Clipper.exe'
$taskkill = Join-Path $env:SystemRoot 'System32\taskkill.exe'
function Write-CloseLog([string]$message) {
    if ($env:CLIPPER_CLOSE_LOG) {
        Add-Content -LiteralPath $env:CLIPPER_CLOSE_LOG -Value "$(Get-Date -Format o) $message"
    }
}
function Get-InstalledClipper {
    # The installer is 32-bit. Get-Process can report an empty Path for a
    # 64-bit Clipper process under WOW64, so resolve paths through CIM first.
    $cim = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -ieq 'Clipper.exe' -and
            $_.ExecutablePath -and
            ($_.ExecutablePath -ieq $installExe)
        })
    if ($cim.Count -gt 0) {
        foreach ($item in $cim) {
            $process = Get-Process -Id $item.ProcessId -ErrorAction SilentlyContinue
            if ($process) { $process }
        }
        return
    }
    $all = @(Get-Process -Name 'Clipper' -ErrorAction SilentlyContinue)
    if ($all.Count -eq 1 -and -not $all[0].Path) {
        return $all
    }
    return @()
}

$running = Get-InstalledClipper
Write-CloseLog "root=$PSScriptRoot installExe=$installExe running=$($running.Count)"
if ($running.Count -eq 0) { exit 0 }

$running | ForEach-Object {
    $_.Refresh()
    $closed = $_.CloseMainWindow()
    Write-CloseLog "CloseMainWindow pid=$($_.Id) result=$closed"
}

$deadline = (Get-Date).AddSeconds(8)
while ((Get-InstalledClipper).Count -gt 0 -and (Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 250
}
Write-CloseLog "after graceful wait running=$((Get-InstalledClipper).Count)"

# CloseMainWindow can report a zero main-window handle for a just-started
# PyInstaller process. Give the OS one more graceful WM_CLOSE attempt before
# resorting to /F.
$running = Get-InstalledClipper
foreach ($process in $running) {
    Write-CloseLog "graceful taskkill pid=$($process.Id)"
    & $taskkill /PID $process.Id /T | Out-Null
}
Start-Sleep -Seconds 3

$running = Get-InstalledClipper
foreach ($process in $running) {
    Write-CloseLog "force taskkill pid=$($process.Id)"
    & $taskkill /F /PID $process.Id /T | Out-Null
}
Start-Sleep -Seconds 1

if ((Get-InstalledClipper).Count -gt 0) { exit 1 }
Write-CloseLog "closed"
# Give Windows a moment to unload the app's DLLs before the installer removes
# _internal. Without this, a just-closed Clipper can leave locked files behind.
Start-Sleep -Seconds 2
exit 0
