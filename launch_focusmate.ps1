$project = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $project
$expectedDatabase = [System.IO.Path]::GetFullPath((Join-Path $project "assistant.db"))
$healthUrl = "http://127.0.0.1:5000/health"

$listener = Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    try {
        $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2
    } catch {
        Write-Error "Port 5000 is already in use by another or older server. Stop that server, then launch Focusmate again."
        exit 1
    }
    if ($health.status -ne "ok" -or -not $health.database -or [System.IO.Path]::GetFullPath($health.database) -ine $expectedDatabase) {
        Write-Error "A different Focusmate installation is running on port 5000. Stop it before launching this copy."
        exit 1
    }
    Start-Process "http://127.0.0.1:5000"
    exit 0
}

$pythonw = Join-Path $project ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pythonw)) {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        Write-Error "Python was not found. Create the project virtual environment and install requirements first."
        exit 1
    }
    $pythonw = Join-Path (Split-Path $python.Source) "pythonw.exe"
    if (-not (Test-Path $pythonw)) { $pythonw = $python.Source }
}
$server = Start-Process -FilePath $pythonw -ArgumentList "app.py" -WorkingDirectory $project -WindowStyle Hidden -PassThru

$ready = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    try {
        $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 1
        if ($health.status -eq "ok" -and $health.database -and [System.IO.Path]::GetFullPath($health.database) -ieq $expectedDatabase) {
            $ready = $true
            break
        }
    } catch {
        Start-Sleep -Milliseconds 500
    }
}

if (-not $ready) {
    Write-Error "Focusmate did not start with the expected database. Check the Python environment and port 5000."
    if (-not $server.HasExited) { Stop-Process -Id $server.Id }
    exit 1
}

Start-Process "http://127.0.0.1:5000"
Wait-Process -Id $server.Id