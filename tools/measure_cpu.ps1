# tools/measure_cpu.ps1
# Sample the CPU usage of the Voice Notes python process, normalized to % of
# TOTAL CPU (CPU-time delta / (wall-time * logical cores)). Run while the app is
# idle, while recording, and during transcription to verify the budget.
#   .\tools\measure_cpu.ps1 -Seconds 15
#   .\tools\measure_cpu.ps1 -Seconds 10 -TargetPid 12345
param([int]$Seconds = 15, [int]$TargetPid = 0)

$cores = [Environment]::ProcessorCount

if ($TargetPid -eq 0) {
    $p = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
         Where-Object { $_.CommandLine -like '*main.py*' } | Select-Object -First 1
    if ($p) { $TargetPid = [int]$p.ProcessId }
}
if ($TargetPid -eq 0) {
    Write-Output "Voice Notes process not found. Start it, or pass -TargetPid <id>."
    exit 1
}
try { $proc = [System.Diagnostics.Process]::GetProcessById($TargetPid) }
catch { Write-Output "PID $TargetPid is not running."; exit 1 }

$t0 = $proc.TotalProcessorTime; $w0 = Get-Date
Start-Sleep -Seconds $Seconds
$proc.Refresh()
$t1 = $proc.TotalProcessorTime; $w1 = Get-Date

$cpuMs  = ($t1 - $t0).TotalMilliseconds
$wallMs = ($w1 - $w0).TotalMilliseconds
$pct = if ($wallMs -gt 0) { ($cpuMs / ($wallMs * $cores)) * 100 } else { 0 }
Write-Output ("PID {0}: {1:N1}% of total CPU over {2}s ({3} logical cores)" -f $TargetPid, $pct, $Seconds, $cores)
