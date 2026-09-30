# Restart Cascadeur after a crash or hang and wait for the MCP bridge. The bridge is started by
# resources\scripts\python\events\scene_opened\mcp_bridge_autostart.py: opening the scene given
# on the command line fires scene_opened (the startup scene does not fire scene_created).
param(
    [int]$TimeoutSec = 60,
    [string]$Scene = "C:\Users\IshikiI\Desktop\Coding\Cascadeur\VibeAnimating\cascadeur-work\animations\punch.casc"
)
$exe = "C:\Users\IshikiI\Software\Cascadeur\cascadeur.exe"
$status = "C:\Users\IshikiI\Desktop\Coding\Cascadeur\VibeAnimating\cascadeur-work\session\status.json"

Get-Process cascadeur -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
# the killed bridge leaves a fresh heartbeat; a new bridge would refuse the directory for 10 s
Remove-Item $status -ErrorAction SilentlyContinue
$started = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
Start-Process -FilePath $exe -ArgumentList "`"$Scene`"" -WorkingDirectory (Split-Path $exe)

$deadline = (Get-Date).AddSeconds($TimeoutSec)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 3
    if (Test-Path $status) {
        try {
            $s = Get-Content $status -Raw | ConvertFrom-Json
            if ($s.heartbeat -gt $started) { Write-Output "bridge up (pid $($s.pid))"; exit 0 }
        } catch {}
    }
}
Write-Output "Cascadeur started, bridge did not come up in $TimeoutSec s"
exit 1
