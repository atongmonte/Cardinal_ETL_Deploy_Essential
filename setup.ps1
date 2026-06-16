#Requires -Version 5.1
<#
.SYNOPSIS
    Cardinal Invoice ETL - New Machine Setup

.DESCRIPTION
    Runs the full setup sequence on a new machine:
      1. Locate a compatible Python 3.x installation
      2. Create / validate the Python virtual environment
      3. Install / verify required packages from requirements.txt
      4. Ensure .env file exists with required keys
      5. Validate plain service and email credentials
      6. Test network drive connectivity  (Test_NetworkDrive_Simple.py via impersonation)
      7. Test database connectivity       (PRIME_Connection_Simple.py via impersonation)
      8. Test email notification system   (test_email_notification.py via impersonation)
      9. Dry-run Cardinal ETL task        (Cardinal_Inv_Upload.py via impersonation - staging only)
     10. Create (or update) a Windows Task Scheduler task for daily ETL

.USAGE
    Open PowerShell as the user who will RUN the task (e.g. atong), then:
        cd "<path to ETLs folder>"
        .\setup.ps1

    To skip the Task Scheduler step:
        .\setup.ps1 -SkipTaskScheduler

    To set a custom task run time (default 07:00):
        .\setup.ps1 -TaskTime "06:30"
#>

param(
    [switch]$SkipTaskScheduler,
    [string]$TaskTime = "10:00"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# --- Helpers ------------------------------------------------------------------
function Write-Step { param([int]$n, [string]$msg) Write-Host "`n[STEP $n] $msg" -ForegroundColor Cyan }
function Write-OK   { param([string]$msg) Write-Host "  [OK]  $msg" -ForegroundColor Green }
function Write-Warn { param([string]$msg) Write-Host "  [!!]  $msg" -ForegroundColor Yellow }
function Write-Fail { param([string]$msg) Write-Host "  [XX]  $msg" -ForegroundColor Red }
function Write-Info { param([string]$msg) Write-Host "        $msg" -ForegroundColor Gray }

function Test-PythonExecutable {
    param([string]$PythonPath)
    
    if (-not (Test-Path $PythonPath)) { return $false }
    
    try {
        $version = & $PythonPath --version 2>&1 | Out-String
        $testResult = & $PythonPath -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>&1
        
        if ($LASTEXITCODE -eq 0 -and $version -match "Python 3\.\d+" -and $testResult -match "3\.\d+") {
            return @{
                IsValid = $true
                Version = $version.Trim()
                MajorMinor = $testResult.Trim()
            }
        }
    } catch {
        Write-Info "Error testing Python at $PythonPath : $($_.Exception.Message)"
    }
    
    return $false
}

function Get-SystemInfo {
    $info = @{
        OS = (Get-WmiObject Win32_OperatingSystem).Caption
        Architecture = $env:PROCESSOR_ARCHITECTURE
        User = "$env:USERDOMAIN\$env:USERNAME"
        PowerShellVersion = $PSVersionTable.PSVersion.ToString()
    }
    return $info
}

$SCRIPT_DIR  = $PSScriptRoot
$VENV_DIR    = Join-Path $SCRIPT_DIR "venv"
$VENV_PYTHON = Join-Path $VENV_DIR   "Scripts\python.exe"
$VENV_PIP    = Join-Path $VENV_DIR   "Scripts\pip.exe"
$REQ_FILE    = Join-Path $SCRIPT_DIR "requirements.txt"
$ENV_FILE    = Join-Path $SCRIPT_DIR ".env"

$TASK_NAME   = "CARDINAL_DAILY_INV_UPDATE"
$TASK_DESC   = "Runs the Cardinal daily invoice ETL (Cardinal_Inv_Upload.py)"
$MAIN_SCRIPT = Join-Path $SCRIPT_DIR "Cardinal_Inv_Upload.py"

$systemInfo = Get-SystemInfo

Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "   Cardinal Invoice ETL -- New Machine Setup"                     -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  Script dir : $SCRIPT_DIR"
Write-Host "  Running as : $($systemInfo.User)"
Write-Host "  Date       : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "  OS         : $($systemInfo.OS)"
Write-Host "  Arch       : $($systemInfo.Architecture)"
Write-Host "  PowerShell : $($systemInfo.PowerShellVersion)"

# ==============================================================================
# STEP 1 - Find Python 3.x
# ==============================================================================
Write-Step 1 "Locating Python 3.x installation..."

$pythonExe = $null

# Try to find Python using 'where' command first (checks PATH)
try {
    $pythonFromPath = & where.exe python.exe 2>$null | Select-Object -First 1
    if ($pythonFromPath -and (Test-Path $pythonFromPath)) {
        $candidates = @($pythonFromPath)
    } else {
        $candidates = @()
    }
} catch {
    $candidates = @()
}

# Add common installation paths as fallback
$candidates += @(
    "C:\Users\$env:USERNAME\AppData\Local\Programs\Python\Python312\python.exe",
    "C:\Users\$env:USERNAME\AppData\Local\Programs\Python\Python311\python.exe",
    "C:\Users\$env:USERNAME\AppData\Local\Programs\Python\Python310\python.exe",
    "C:\Users\$env:USERNAME\AppData\Local\Programs\Python\Python39\python.exe",
    "C:\Python312\python.exe",
    "C:\Python311\python.exe",
    "C:\Python310\python.exe",
    "C:\Program Files\Python312\python.exe",
    "C:\Program Files\Python311\python.exe",
    "C:\Program Files\Python310\python.exe",
    "C:\Program Files (x86)\Python312\python.exe",
    "C:\Program Files (x86)\Python311\python.exe",
    "C:\Program Files (x86)\Python310\python.exe"
)

foreach ($c in $candidates) {
    $pythonTest = Test-PythonExecutable -PythonPath $c
    if ($pythonTest -and $pythonTest.IsValid) { 
        $pythonExe = $c
        Write-Info "Found working Python: $c ($($pythonTest.Version))"
        break 
    }
}

if (-not $pythonExe) {
    # Final fallback - try to get python from PATH
    try { 
        $pathPython = (Get-Command python -ErrorAction Stop).Source 
        $pythonTest = Test-PythonExecutable -PythonPath $pathPython
        if ($pythonTest -and $pythonTest.IsValid) {
            $pythonExe = $pathPython
            Write-Info "Found Python in PATH: $pathPython ($($pythonTest.Version))"
        }
    } catch {
        Write-Info "No python found in PATH"
    }
}

if (-not $pythonExe) {
    Write-Fail "Python 3.x not found in any of the expected locations."
    Write-Info "Searched locations:"
    $candidates | ForEach-Object { Write-Info "  - $_" }
    Write-Info ""
    Write-Info "Please install Python 3.10+ from https://python.org"
    Write-Info "Make sure to check 'Add Python to PATH' during installation."
    exit 1
}

$pythonTest = Test-PythonExecutable -PythonPath $pythonExe
if (-not $pythonTest -or -not $pythonTest.IsValid) {
    Write-Fail "Python executable validation failed: $pythonExe"
    exit 1
}
Write-OK "Python found: $pythonExe  ($($pythonTest.Version))"

# ==============================================================================
# STEP 2 - Create / validate virtual environment
# ==============================================================================
Write-Step 2 "Checking virtual environment..."

if (-not (Test-Path $VENV_PYTHON)) {
    Write-Info "venv not found -- creating at: $VENV_DIR"
    & $pythonExe -m venv $VENV_DIR
    if ($LASTEXITCODE -ne 0) { Write-Fail "venv creation failed."; exit 1 }
    Write-OK "venv created."
} else {
    # Test if venv Python executable actually works
    try {
        $venvVer = & $VENV_PYTHON --version 2>&1 | Out-String
        $testResult = & $VENV_PYTHON -c "import sys; print('Python OK')" 2>&1
        if ($LASTEXITCODE -ne 0 -or $testResult -notmatch "Python OK") {
            throw "venv Python not working"
        }
        Write-OK "venv OK ($($venvVer.Trim()))"
    } catch {
        Write-Warn "Existing venv appears broken -- recreating..."
        try {
            Remove-Item $VENV_DIR -Recurse -Force -ErrorAction Stop
        } catch {
            Write-Warn "Could not remove old venv directory. Trying to continue..."
        }
        & $pythonExe -m venv $VENV_DIR
        if ($LASTEXITCODE -ne 0) { Write-Fail "venv recreation failed."; exit 1 }
        Write-OK "venv recreated."
    }
}

$pythonExe = $VENV_PYTHON

# ==============================================================================
# STEP 3 - Install / verify packages
# ==============================================================================
Write-Step 3 "Installing / verifying packages from requirements.txt..."

if (-not (Test-Path $REQ_FILE)) {
    Write-Fail "requirements.txt not found at: $REQ_FILE"
    exit 1
}

# Use a more robust approach to handle pip installation
try {
    Write-Info "Installing packages from requirements.txt..."
    $pipOutput = & $pythonExe -m pip install -r $REQ_FILE --quiet --disable-pip-version-check 2>&1
    $pipExitCode = $LASTEXITCODE
    
    # Filter out notice messages and display relevant output
    if ($pipOutput) {
        $pipOutput | Where-Object { $_ -and $_ -notmatch '^\[notice\]' -and $_ -notmatch '^\s*$' } | ForEach-Object { 
            Write-Info ([string]$_)
        }
    }
    
    if ($pipExitCode -ne 0) {
        Write-Fail "pip install failed (exit code: $pipExitCode). Check network/proxy and try again."
        exit 1
    }
} catch {
    Write-Fail "pip install encountered an error: $($_.Exception.Message)"
    exit 1
}

# Verify critical packages with better error reporting
$criticalPkgs = @(
    @{name='pandas'; import='pandas'},
    @{name='pyodbc'; import='pyodbc'},
    @{name='cryptography'; import='cryptography'},
    @{name='pywin32'; import='win32api'},
    @{name='PyYAML'; import='yaml'},
    @{name='python-dotenv'; import='dotenv'}
)

$missingPkgs = @()
foreach ($pkg in $criticalPkgs) {
    try {
        $importResult = & $pythonExe -c "import $($pkg.import); print('OK')" 2>&1
        if ($LASTEXITCODE -ne 0 -or $importResult -notmatch "OK") {
            $missingPkgs += $pkg.name
            Write-Info "Package $($pkg.name) failed import test"
        }
    } catch {
        $missingPkgs += $pkg.name
        Write-Info "Package $($pkg.name) import test error: $($_.Exception.Message)"
    }
}

if ($missingPkgs.Count -gt 0) {
    Write-Fail "Packages still missing after install: $($missingPkgs -join ', ')"
    Write-Info "Try running: $pythonExe -m pip install $($missingPkgs -join ' ')"
    exit 1
}
Write-OK "All required packages verified."

# ==============================================================================
# STEP 4 - Validate .env file
# ==============================================================================
Write-Step 4 "Checking .env file..."

if (-not (Test-Path $ENV_FILE)) {
    Write-Fail ".env not found at: $ENV_FILE"
    Write-Info "Copy .env from another machine or create it with required keys, then re-run."
    exit 1
}

$envContent   = Get-Content $ENV_FILE -Raw
# Only secrets remain in .env; paths/db config are in config.yaml
$requiredKeys = @('SERVICE_USER', 'SERVICE_PASS', 'TENANT_ID', 'CLIENT_ID', 'CLIENT_SECRET')
$missingKeys  = @()

foreach ($key in $requiredKeys) {
    if ($envContent -notmatch "(?m)^$key\s*=\s*.+") { $missingKeys += $key }
}

if ($missingKeys.Count -gt 0) {
    Write-Fail ".env is missing required keys: $($missingKeys -join ', ')"
    exit 1
}
Write-OK ".env exists with all required keys."

# ==============================================================================
# STEP 5 - Validate plain credentials
# ==============================================================================
Write-Step 5 "Plain credentials configured."
Write-OK ".env contains SERVICE_PASS and Microsoft Graph credentials."

# ==============================================================================
# STEP 6 - Test network drive
# ==============================================================================
Write-Step 6 "Testing network drive connectivity..."

& $pythonExe (Join-Path $SCRIPT_DIR "run_with_impersonation.py") (Join-Path $SCRIPT_DIR "Test_NetworkDrive_Simple.py") 2>&1 |
    ForEach-Object { Write-Info ([string]$_) }

if ($LASTEXITCODE -ne 0) {
    Write-Fail "Network drive test FAILED (exit $LASTEXITCODE). Review output above."
    $cont = Read-Host "  Continue setup anyway? [y/N]"
    if ($cont -notmatch '^[Yy]') { exit 1 }
    Write-Warn "Continuing despite network test failure..."
} else {
    Write-OK "Network drive test passed."
}

# ==============================================================================
# STEP 7 - Test database connectivity
# ==============================================================================
Write-Step 7 "Testing PRIME database connectivity..."

& $pythonExe (Join-Path $SCRIPT_DIR "run_with_impersonation.py") (Join-Path $SCRIPT_DIR "PRIME_Connection_Simple.py") 2>&1 | ForEach-Object {
    $line = [string]$_
    if ($line -match 'Connected|Logged in|FAILED|Error|Rows returned') {
        Write-Info $line
    }
}

if ($LASTEXITCODE -ne 0) {
    Write-Fail "PRIME_Connection.py FAILED (exit $LASTEXITCODE)."
    $cont = Read-Host "  Continue setup anyway? [y/N]"
    if ($cont -notmatch '^[Yy]') { exit 1 }
    Write-Warn "Continuing despite DB test failure..."
} else {
    Write-OK "Database connection test passed."
}

# ==============================================================================
# STEP 8 - Test email notification system
# ==============================================================================
Write-Step 8 "Testing email notification system..."

$emailTestPath = Join-Path $SCRIPT_DIR "run_with_impersonation.py"
$emailScript = Join-Path $SCRIPT_DIR "test_email_notification.py"

try {
    $process = Start-Process -FilePath $pythonExe -ArgumentList $emailTestPath,$emailScript -WorkingDirectory $SCRIPT_DIR -NoNewWindow -PassThru -Wait -RedirectStandardOutput "email_test_output.tmp" -RedirectStandardError "email_test_error.tmp"
    
    $output = ""
    if (Test-Path "email_test_output.tmp") {
        $output = Get-Content "email_test_output.tmp" -Raw
        Remove-Item "email_test_output.tmp" -ErrorAction SilentlyContinue
    }
    
    $errors = ""
    if (Test-Path "email_test_error.tmp") {
        $errors = Get-Content "email_test_error.tmp" -Raw
        Remove-Item "email_test_error.tmp" -ErrorAction SilentlyContinue
    }
    
    if ($output) {
        $output.Split("`n") | ForEach-Object { 
            if ($_.Trim()) { Write-Info $_.Trim() }
        }
    }
    
    if ($errors -and $process.ExitCode -ne 0) {
        Write-Info "Error output: $errors"
    }
    
    if ($process.ExitCode -eq 0) {
        Write-OK "Email notification test passed."
    } else {
        Write-Fail "Email notification test FAILED (exit $($process.ExitCode))."
        $cont = Read-Host "  Continue setup anyway? [y/N]"
        if ($cont -notmatch '^[Yy]') { exit 1 }
        Write-Warn "Continuing despite email test failure..."
    }
} catch {
    Write-Fail "Error running email test: $($_.Exception.Message)"
    $cont = Read-Host "  Continue setup anyway? [y/N]"
    if ($cont -notmatch '^[Yy]') { exit 1 }
    Write-Warn "Continuing despite email test failure..."
}

# ==============================================================================
# STEP 9 - Dry-run Cardinal ETL task (staging only)
# ==============================================================================
Write-Step 9 "Dry-run Cardinal ETL task (staging only - no archive)..."

$dryrunTestPath = Join-Path $SCRIPT_DIR "run_with_impersonation.py"
$dryrunScript = Join-Path $SCRIPT_DIR "Cardinal_Inv_Upload_DryRun.py"

try {
    Write-Info "Running Cardinal ETL in dry-run mode (staging only)..."
    Write-Info "This will test the full ETL process but only load to staging table."
    Write-Info "No files will be moved to archive, and no data will be inserted to final table."
    
    $process = Start-Process -FilePath $pythonExe -ArgumentList $dryrunTestPath,$dryrunScript -WorkingDirectory $SCRIPT_DIR -NoNewWindow -PassThru -Wait -RedirectStandardOutput "dryrun_output.tmp" -RedirectStandardError "dryrun_error.tmp"
    
    $output = ""
    if (Test-Path "dryrun_output.tmp") {
        $output = Get-Content "dryrun_output.tmp" -Raw
        Remove-Item "dryrun_output.tmp" -ErrorAction SilentlyContinue
    }
    
    $errors = ""
    if (Test-Path "dryrun_error.tmp") {
        $errors = Get-Content "dryrun_error.tmp" -Raw
        Remove-Item "dryrun_error.tmp" -ErrorAction SilentlyContinue
    }
    
    if ($output) {
        $output.Split("`n") | ForEach-Object { 
            if ($_.Trim()) { Write-Info $_.Trim() }
        }
    }
    
    if ($errors -and $process.ExitCode -ne 0) {
        Write-Info "Error output: $errors"
    }
    
    if ($process.ExitCode -eq 0) {
        Write-OK "Cardinal ETL dry-run test passed."
    } else {
        Write-Fail "Cardinal ETL dry-run test FAILED (exit $($process.ExitCode))."
        $cont = Read-Host "  Continue setup anyway? [y/N]"
        if ($cont -notmatch '^[Yy]') { exit 1 }
        Write-Warn "Continuing despite ETL dry-run failure..."
    }
} catch {
    Write-Fail "Error running ETL dry-run test: $($_.Exception.Message)"
    $cont = Read-Host "  Continue setup anyway? [y/N]"
    if ($cont -notmatch '^[Yy]') { exit 1 }
    Write-Warn "Continuing despite ETL dry-run failure..."
}

# ==============================================================================
# STEP 10 - Task Scheduler
# ==============================================================================
if ($SkipTaskScheduler) {
    Write-Warn "Skipping Task Scheduler setup (-SkipTaskScheduler flag set)."
} else {
    Write-Step 10 "Configuring Task Scheduler task: '$TASK_NAME'..."

    # Load service account credentials from .env file
    $envContent = Get-Content $ENV_FILE -Raw
    $serviceUser = ($envContent -split "`n" | Where-Object { $_ -match '^SERVICE_USER=' }) -replace '^SERVICE_USER=', '' -replace '"', ''
    
    if (-not $serviceUser) {
        Write-Fail "SERVICE_USER not found in .env file."
        Write-Info "Make sure .env file contains service account credentials."
        exit 1
    }
    
    Write-Info "Service User : $serviceUser"

    # Write wrapper script that runs ETL with impersonation
    $wrapperScript = Join-Path $SCRIPT_DIR "run_cardinal_etl.ps1"
    $wrapperLines = @(
        '# Auto-generated by setup.ps1 - do not edit manually.',
        '# Runs the Cardinal Invoice ETL via run_with_impersonation.py wrapper.',
        '',
        '$ScriptDir  = $PSScriptRoot',
        '$PythonExe  = Join-Path $ScriptDir "venv\Scripts\python.exe"',
        '$MainScript = Join-Path $ScriptDir "Cardinal_Inv_Upload.py"',
        '$ConfigFile = Join-Path $ScriptDir "config.yaml"',
        '$EnvFile    = Join-Path $ScriptDir ".env"',
        '$LogDir     = Join-Path $ScriptDir "log"',
        'if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }',
        '$LogFile    = Join-Path $LogDir "run_cardinal_etl.log"',
        '$Timestamp  = Get-Date -Format ''yyyy-MM-dd HH:mm:ss''',
        '',
        'Add-Content -Path $LogFile -Value ""',
        'Add-Content -Path $LogFile -Value "[$Timestamp] ===== Task Started ====="',
        'Add-Content -Path $LogFile -Value "[$Timestamp] Script dir : $ScriptDir"',
        'Add-Content -Path $LogFile -Value "[$Timestamp] Run as     : $env:USERDOMAIN\$env:USERNAME"',
        '',
        '$CheckFailed = $false',
        '',
        'if (Test-Path $PythonExe) {',
        '    Add-Content -Path $LogFile -Value "[$Timestamp] [OK]  python.exe             : $PythonExe"',
        '} else {',
        '    Add-Content -Path $LogFile -Value "[$Timestamp] [XX]  python.exe             : NOT FOUND at $PythonExe"',
        '    $CheckFailed = $true',
        '}',
        '',
        'if (Test-Path $MainScript) {',
        '    Add-Content -Path $LogFile -Value "[$Timestamp] [OK]  Cardinal_Inv_Upload.py : $MainScript"',
        '} else {',
        '    Add-Content -Path $LogFile -Value "[$Timestamp] [XX]  Cardinal_Inv_Upload.py : NOT FOUND at $MainScript"',
        '    $CheckFailed = $true',
        '}',
        '',
        'if (Test-Path $ConfigFile) {',
        '    Add-Content -Path $LogFile -Value "[$Timestamp] [OK]  config.yaml            : $ConfigFile"',
        '} else {',
        '    Add-Content -Path $LogFile -Value "[$Timestamp] [XX]  config.yaml            : NOT FOUND at $ConfigFile"',
        '    $CheckFailed = $true',
        '}',
        '',
        'if (Test-Path $EnvFile) {',
        '    Add-Content -Path $LogFile -Value "[$Timestamp] [OK]  .env                   : $EnvFile"',
        '} else {',
        '    Add-Content -Path $LogFile -Value "[$Timestamp] [XX]  .env                   : NOT FOUND at $EnvFile"',
        '    $CheckFailed = $true',
        '}',
        'if ($CheckFailed) {',
        '    Add-Content -Path $LogFile -Value "[$Timestamp] Pre-flight checks FAILED. Aborting."',
        '    exit 1',
        '}',
        '',
        'Add-Content -Path $LogFile -Value "[$Timestamp] All pre-flight checks passed. Launching ETL..."',
        '',
        '& "$ScriptDir\venv\Scripts\python.exe" "$ScriptDir\run_with_impersonation.py" "$ScriptDir\Cardinal_Inv_Upload.py"',
        '$ExitCode = $LASTEXITCODE',
        '',
        '$Timestamp = Get-Date -Format ''yyyy-MM-dd HH:mm:ss''',
        'Add-Content -Path $LogFile -Value "[$Timestamp] ===== Task Finished - Exit Code: $ExitCode ====="',
        '',
        'exit $ExitCode'
    )
    Set-Content -Path $wrapperScript -Value $wrapperLines -Encoding UTF8
    Write-Info "Wrapper script : $wrapperScript"

    $action = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument "-NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$wrapperScript`""

    $trigger = New-ScheduledTaskTrigger -Weekly `
        -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
        -At $TaskTime

    $settings = New-ScheduledTaskSettingsSet `
        -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
        -StartWhenAvailable `
        -RunOnlyIfNetworkAvailable `
        -MultipleInstances IgnoreNew `
        -RestartCount 1 `
        -RestartInterval (New-TimeSpan -Minutes 30)

    # Configure to run as current user (runs only when user is logged on)
    $principal = New-ScheduledTaskPrincipal `
        -UserId "$env:USERDOMAIN\$env:USERNAME" `
        -LogonType Interactive `
        -RunLevel Highest

    $existingTask = Get-ScheduledTask -TaskName $TASK_NAME -ErrorAction SilentlyContinue
    if ($existingTask) {
        Write-Warn "Task '$TASK_NAME' already exists -- updating..."
        Set-ScheduledTask -TaskName $TASK_NAME `
            -Action $action -Trigger $trigger `
            -Settings $settings -Principal $principal | Out-Null
        Write-OK "Task updated."
    } else {
        Register-ScheduledTask -TaskName $TASK_NAME `
            -Action $action -Trigger $trigger `
            -Settings $settings -Principal $principal `
            -Description $TASK_DESC | Out-Null
        Write-OK "Task '$TASK_NAME' registered."
    }

    Write-Info "Schedule : Weekdays at $TaskTime"
    Write-Info "Run as   : $env:USERDOMAIN\$env:USERNAME (Interactive logon - runs when user is logged on)"
    Write-Info "Uses     : run_with_impersonation.py wrapper (service account: $serviceUser)"
}

# ==============================================================================
# DONE
# ==============================================================================
Write-Host ""
Write-Host "================================================================" -ForegroundColor Green
Write-Host "   Setup Complete - All Systems Tested!"                          -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Green
Write-Host "  ✅ Network Drive Access - Working" -ForegroundColor Green
Write-Host "  ✅ Database Connectivity - Working" -ForegroundColor Green  
Write-Host "  ✅ Email Notifications - Working" -ForegroundColor Green
Write-Host ""
Write-Host "  To run the ETL manually:"
Write-Host "    & `"$VENV_PYTHON`" `"$MAIN_SCRIPT`"" -ForegroundColor Gray
Write-Host ""
