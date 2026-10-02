# Adds this project directory to your user PATH so you can run 'winwarden' from anywhere.
# Run once:  powershell -ExecutionPolicy Bypass -File install.ps1

$projectDir = $PSScriptRoot
$current    = [Environment]::GetEnvironmentVariable("PATH", "User")

if ($current -like "*$projectDir*") {
    Write-Host "Already on PATH: $projectDir"
} else {
    [Environment]::SetEnvironmentVariable("PATH", "$current;$projectDir", "User")
    Write-Host "Added to user PATH: $projectDir"
    Write-Host ""
    Write-Host "Open a NEW terminal and type:  winwarden"
    Write-Host "(Current terminals won't see the change until restarted.)"
}
