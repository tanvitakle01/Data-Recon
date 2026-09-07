```powershell
# Start frontend and backend in separate VS Code terminals

$ProjectRoot = $PSScriptRoot

Write-Host "Starting backend..." -ForegroundColor Green

# Create a new terminal for backend
code --reuse-window --command "workbench.action.terminal.new"

Start-Sleep -Seconds 1

# Start backend
$backendCommand = "Set-Location '$ProjectRoot'; .\venv\Scripts\Activate.ps1; python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000"

Write-Host "Backend command:"
Write-Host $backendCommand

# Start frontend in another terminal
Write-Host "Starting frontend..." -ForegroundColor Green

code --reuse-window --command "workbench.action.terminal.new"

Start-Sleep -Seconds 1

$frontendCommand = "Set-Location '$ProjectRoot'; Set-Location frontend; npm run dev"

Write-Host "Frontend command:"
Write-Host $frontendCommand

Write-Host ""
Write-Host "Frontend and backend terminals created." -ForegroundColor Cyan
```
