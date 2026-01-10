$targetDir = "C:\Log\benedictjun"
$currentPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($currentPath -notlike "*$targetDir*") {
    $newPath = $currentPath + ";$targetDir"
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    Write-Host "Success! Added $targetDir to your User PATH."
    Write-Host "Please RESTART your PowerShell terminal for the changes to take effect."
    Write-Host "After restarting, you can type 'jun' from anywhere to start your project."
} else {
    Write-Host "Good news! $targetDir is already in your User PATH."
    Write-Host "If 'jun' still doesn't work, try restarting your terminal."
}
