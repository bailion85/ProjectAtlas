$ErrorActionPreference = "Stop"
$taskName = "Project Atlas Holdings Research"
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Removed: $taskName"
} else {
    Write-Host "Task is not installed: $taskName"
}