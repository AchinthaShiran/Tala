# One-line installer for Windows (PowerShell):
#   irm https://raw.githubusercontent.com/AchinthaShiran/Tala/main/install.ps1 | iex
#
# Installs the app in its own isolated environment (uv or pipx), then starts the setup wizard.
# Rebranding: change the variables below (they mirror src/assistant/domain/branding.py).
$AppName = "Tala"
$Command = "tala"
$EnvPrefix = "TALA"
$DefaultPackage = "tala-ai"
$MinPython = [version]"3.11"

function Get-Setting([string]$Suffix) {
    [Environment]::GetEnvironmentVariable("${EnvPrefix}_$Suffix")
}

# Runs "<exe> <args>" with no console input and a time limit; returns its output, or $null if it
# failed or hung (the Microsoft Store "python" stubs and some launchers can wait for a keypress).
function Get-ProbeOutput([string]$Exe, [string[]]$ProbeArgs, [int]$Seconds = 15) {
    try {
        $info = New-Object System.Diagnostics.ProcessStartInfo
        $info.FileName = $Exe
        $info.Arguments = ($ProbeArgs | ForEach-Object { if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ } }) -join " "
        $info.UseShellExecute = $false
        $info.RedirectStandardOutput = $true
        $info.RedirectStandardError = $true
        $info.RedirectStandardInput = $true
        $info.CreateNoWindow = $true
        $proc = [System.Diagnostics.Process]::Start($info)
        $proc.StandardInput.Close()
        $out = $proc.StandardOutput.ReadToEndAsync()
        if (-not $proc.WaitForExit($Seconds * 1000)) {
            try { $proc.Kill() } catch { }
            return $null
        }
        if ($proc.ExitCode -ne 0) { return $null }
        return $out.Result.Trim()
    } catch {
        return $null
    }
}

function Find-Python {
    $script:PythonNotes = @()
    foreach ($candidate in @("py", "python3", "python")) {
        $found = Get-Command $candidate -ErrorAction SilentlyContinue
        if (-not $found) { $script:PythonNotes += "${candidate}: not found"; continue }
        [string[]]$pyArgs = if ($candidate -eq "py") { @("-3") } else { @() }  # typed: a lone "-3" must stay an array
        $text = Get-ProbeOutput $found.Source ($pyArgs + @("-c", "import sys; print('.'.join(map(str, sys.version_info[:2])))"))
        if ($text -match '^\d+\.\d+$' -and ([version]$text -ge $MinPython)) { return @($found.Source) + $pyArgs }
        $answer = if ($text) { "version $text" } else { "no answer" }
        $script:PythonNotes += "$($found.Source): $answer"
    }
    return $null
}

function Install-App {
    $source = Get-Setting "SOURCE"
    if (-not $source) { $source = $DefaultPackage }
    Write-Host "Installing $AppName ... (the first install downloads several packages and can take a few minutes)"

    if (Get-Command uv -ErrorAction SilentlyContinue) {
        Write-Host "Using uv."
        uv tool install --force $source
        uv tool update-shell 2>$null | Out-Null
    } elseif (Get-Command pipx -ErrorAction SilentlyContinue) {
        Write-Host "Using pipx."
        pipx install --force $source
        pipx ensurepath 2>$null | Out-Null
    } else {
        Write-Host "Looking for Python ..."
        $python = Find-Python
        if (-not $python) {
            $checked = $script:PythonNotes -join "; "
            throw "Python $MinPython or newer is required. Install it from https://www.python.org/downloads/ and run this again. (Checked: $checked)"
        }
        $exe = $python[0]
        $prefix = @($python | Select-Object -Skip 1)
        Write-Host "Installing pipx (a few seconds) ..."
        & $exe @prefix -m pip install --user --disable-pip-version-check pipx
        if ($LASTEXITCODE -ne 0) { throw "Could not install pipx. Install pipx or uv, then run this again." }
        & $exe @prefix -m pipx ensurepath 2>$null | Out-Null
        & $exe @prefix -m pipx install --force $source
        if ($LASTEXITCODE -ne 0) { throw "pipx could not install $source." }
    }

    # Pick up PATH changes made by the installer in this session.
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")

    $installed = Get-Command $Command -ErrorAction SilentlyContinue
    if (-not $installed) {
        Write-Host ""
        Write-Host "$AppName is installed, but '$Command' is not on your PATH yet."
        Write-Host "Open a new terminal, then run: $Command setup"
        return
    }

    Write-Host ""
    if (Get-Setting "NO_SETUP") {
        Write-Host "Installed. Run '$Command setup' to configure it."
    } else {
        & $installed.Source setup
    }
}

try {
    Install-App
} catch {
    Write-Host "Error: $($_.Exception.Message)" -ForegroundColor Red
}
