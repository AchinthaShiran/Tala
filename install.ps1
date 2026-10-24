# One-line installer for Windows (PowerShell):
#   irm <URL-of-this-file> | iex
#
# Installs the app in its own isolated environment (uv or pipx), then starts the setup wizard.
# Rebranding: change the variables below (they mirror src/assistant/domain/branding.py).
$AppName = "Tala"
$Command = "tala"
$EnvPrefix = "TALA"
$DefaultPackage = "tala-assistant"
$MinPython = [version]"3.11"

function Get-Setting([string]$Suffix) {
    [Environment]::GetEnvironmentVariable("${EnvPrefix}_$Suffix")
}

function Find-Python {
    foreach ($candidate in @("py", "python3", "python")) {
        $found = Get-Command $candidate -ErrorAction SilentlyContinue
        if (-not $found) { continue }
        $pyArgs = if ($candidate -eq "py") { @("-3") } else { @() }
        try {
            $text = (& $found.Source @pyArgs -c "import sys; print('.'.join(map(str, sys.version_info[:2])))" 2>$null)
            if ($text -and ([version]$text -ge $MinPython)) { return @($found.Source) + $pyArgs }
        } catch { continue }
    }
    return $null
}

function Install-App {
    $source = Get-Setting "SOURCE"
    if (-not $source) { $source = $DefaultPackage }
    Write-Host "Installing $AppName ..."

    if (Get-Command uv -ErrorAction SilentlyContinue) {
        Write-Host "Using uv."
        uv tool install --force $source
        uv tool update-shell 2>$null | Out-Null
    } elseif (Get-Command pipx -ErrorAction SilentlyContinue) {
        Write-Host "Using pipx."
        pipx install --force $source
        pipx ensurepath 2>$null | Out-Null
    } else {
        $python = Find-Python
        if (-not $python) {
            throw "Python $MinPython or newer is required. Install it from https://www.python.org/downloads/ and run this again."
        }
        $exe = $python[0]
        $prefix = @($python | Select-Object -Skip 1)
        Write-Host "Installing pipx ..."
        & $exe @prefix -m pip install --user --quiet pipx
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
