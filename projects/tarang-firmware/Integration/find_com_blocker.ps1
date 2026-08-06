# Find processes that might be holding COM11
Write-Host "`n=== Processes likely holding COM11 ===" -ForegroundColor Yellow

$suspects = @("java", "studio", "putty", "python", "serial", "tera", "cool", "real", "herc", "jlink", "commander")
foreach ($name in $suspects) {
    Get-Process -Name "*$name*" -ErrorAction SilentlyContinue | ForEach-Object {
        Write-Host ("  PID={0}  Name={1}  Title={2}" -f $_.Id, $_.Name, $_.MainWindowTitle)
    }
}

Write-Host "`n=== All processes with open handles to COM11 (via mode) ===" -ForegroundColor Yellow
try {
    $mode = cmd /c "mode COM11" 2>&1
    Write-Host $mode
} catch {
    Write-Host "  COM11 not accessible"
}

Write-Host "`nDone."
