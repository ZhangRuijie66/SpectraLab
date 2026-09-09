# Absorption Spectrum Visualization Tool Launcher (PowerShell)
# PowerShell has better UTF-8 support than batch files

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Absorption Spectrum Visualization Tool" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Change to script directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

Write-Host "Current directory: $scriptDir" -ForegroundColor Yellow
Write-Host ""

# Check Python
Write-Host "[1/4] Checking Python..." -ForegroundColor Green
try {
    $pythonVersion = python --version 2>&1
    Write-Host "Python found: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Python not found" -ForegroundColor Red
    Write-Host "Please install Python" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host ""

# Check dependencies
Write-Host "[2/4] Checking dependencies..." -ForegroundColor Green
$depCheck = python -c "import PyQt5, matplotlib, numpy, scipy, pandas" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Missing dependencies!" -ForegroundColor Red
    Write-Host "Please run: pip install PyQt5 matplotlib numpy scipy pandas" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "[OK] Dependencies found" -ForegroundColor Green
Write-Host ""

# Check startup script
Write-Host "[3/4] Checking startup script..." -ForegroundColor Green
if (-not (Test-Path "start_gui.py")) {
    Write-Host "[ERROR] start_gui.py not found" -ForegroundColor Red
    Write-Host "Current directory: $scriptDir" -ForegroundColor Yellow
    Write-Host ""
    Get-ChildItem -Filter "*.py" | Select-Object Name
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "[OK] start_gui.py found" -ForegroundColor Green
Write-Host ""

# Start GUI
Write-Host "[4/4] Starting GUI program..." -ForegroundColor Green
Write-Host "TIP: If window does not appear, check taskbar or press Alt+Tab" -ForegroundColor Yellow
Write-Host ""

python start_gui.py

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Program exited with code: $LASTEXITCODE" -ForegroundColor Red
} else {
    Write-Host "[OK] Program exited normally, code: $LASTEXITCODE" -ForegroundColor Green
}
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "If GUI window did not appear:" -ForegroundColor Yellow
Write-Host "1. Check taskbar for 'Absorption Spectrum Visualization Tool'" -ForegroundColor White
Write-Host "2. Press Alt+Tab to switch windows" -ForegroundColor White
Write-Host "3. Check error messages above (if any)" -ForegroundColor White
Write-Host ""
Read-Host "Press Enter to exit"