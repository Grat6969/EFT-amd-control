# Updates Tarkov Display to the latest version from GitHub.
# Your profiles and settings live in %APPDATA%\TarkovDisplay and are not touched.

$ErrorActionPreference = 'Stop'
$Repo = 'Grat6969/EFT-amd-control'
$Branch = 'claude/tarkov-display-optimizer-30yah9'

$AppDir = $PSScriptRoot
$Package = Join-Path $AppDir 'tarkov_display'
$Backup = Join-Path $AppDir 'tarkov_display.old'
$Tmp = Join-Path ([IO.Path]::GetTempPath()) ('TarkovDisplay-update-' + [guid]::NewGuid())

Write-Host "Updating Tarkov Display in $AppDir"
Write-Host ''

$running = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*tarkov_display*' -or $_.Name -eq 'TarkovDisplay.exe' }
if ($running) {
    Write-Host 'Tarkov Display is still running. Close it (and any console running it), then run update.bat again.' -ForegroundColor Yellow
    exit 1
}

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
New-Item -ItemType Directory -Path $Tmp | Out-Null
try {
    Write-Host 'Downloading latest version...'
    $zip = Join-Path $Tmp 'update.zip'
    Invoke-WebRequest -Uri "https://github.com/$Repo/archive/refs/heads/$Branch.zip" -OutFile $zip -UseBasicParsing
    Expand-Archive -Path $zip -DestinationPath (Join-Path $Tmp 'x')
    $src = (Get-ChildItem (Join-Path $Tmp 'x') -Directory | Select-Object -First 1).FullName
    if (-not $src -or -not (Test-Path (Join-Path $src 'tarkov_display\__init__.py'))) {
        throw 'The download does not look like Tarkov Display.'
    }

    # Replace the code folder as a whole so files removed upstream don't linger,
    # keeping the old copy until the new one is in place.
    if (Test-Path $Backup) { Remove-Item $Backup -Recurse -Force }
    if (Test-Path $Package) { Rename-Item $Package 'tarkov_display.old' }
    try {
        Copy-Item -Path (Join-Path $src '*') -Destination $AppDir -Recurse -Force
    } catch {
        if (Test-Path $Package) { Remove-Item $Package -Recurse -Force }
        if (Test-Path $Backup) { Rename-Item $Backup 'tarkov_display' }
        throw
    }
    if (Test-Path $Backup) { Remove-Item $Backup -Recurse -Force }
    Get-ChildItem $AppDir -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force

    try {
        $commit = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/commits/$Branch" -UseBasicParsing
        $title = ($commit.commit.message -split "`n")[0]
        Write-Host "Latest change: $title"
    } catch { }

    if (Get-Command python -ErrorAction SilentlyContinue) {
        Write-Host 'Checking Python packages...'
        python -m pip install --quiet --disable-pip-version-check -r (Join-Path $AppDir 'requirements.txt')
    }

    Write-Host ''
    Write-Host 'Update complete. Start the app with run.bat' -ForegroundColor Green
} catch {
    Write-Host ''
    Write-Host "Update failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'Your existing copy was left as it was.'
    exit 1
} finally {
    Remove-Item $Tmp -Recurse -Force -ErrorAction SilentlyContinue
}
