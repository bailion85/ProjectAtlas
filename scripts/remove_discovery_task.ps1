$ErrorActionPreference = "Stop"
$taskName = "Project Atlas Daily Discovery"

if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Removed: $taskName"
}
else {
    Write-Host "The Atlas Discovery task is not installed."
}
