param([string]$Destination = '', [switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem
$manifest = Get-Content -Raw -LiteralPath "$PSScriptRoot\manifest.json" | ConvertFrom-Json
if (-not $Destination) { $Destination = Join-Path $env:LOCALAPPDATA ($manifest.project + '-avx1-' + $manifest.channel) }
foreach ($item in $manifest.files) {
    $file = Join-Path $PSScriptRoot $item.path
    if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ne $item.sha256) { throw "Checksum mismatch: $($item.path)" }
}
if ($CheckOnly) { Write-Output 'Package checksums OK'; exit 0 }
if ($manifest.project -eq 'conduit') {
    Write-Output 'Install the APK on an Android ARM64 device. The fork uses its own application ID and signing key.'
    exit 0
}
if ($manifest.project -eq 'desktop') {
    $application = Join-Path $PSScriptRoot 'desktop'
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    Copy-Item -LiteralPath $application -Destination $Destination -Recurse -Force
    Write-Output "Launch: $Destination\desktop\open-webui.exe"
    exit 0
}
if (Test-Path -LiteralPath (Join-Path $Destination 'python')) { throw 'Choose a new empty destination to preserve existing data.' }
New-Item -ItemType Directory -Path $Destination -Force | Out-Null
$runtimeZip = Join-Path $Destination 'python-runtime.tar.gz'
Invoke-WebRequest -UseBasicParsing -Uri $manifest.python.url -OutFile $runtimeZip
if ((Get-FileHash -LiteralPath $runtimeZip -Algorithm SHA256).Hash.ToLowerInvariant() -ne $manifest.python.sha256) { throw 'Python checksum mismatch' }
$runtime = Join-Path $Destination 'python'
& tar.exe -xzf $runtimeZip -C $Destination
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $runtime 'python.exe'))) { throw 'Python extraction failed' }
Remove-Item -LiteralPath $runtimeZip
$site = Join-Path $runtime 'Lib\site-packages'
New-Item -ItemType Directory -Path $site -Force | Out-Null
$pip = Get-ChildItem -LiteralPath "$PSScriptRoot\bootstrap" -Filter 'pip-*.whl' | Select-Object -First 1
if (-not (Test-Path -LiteralPath (Join-Path $site 'pip'))) { [IO.Compression.ZipFile]::ExtractToDirectory($pip.FullName, $site) }
$python = Join-Path $runtime 'python.exe'
$wheels = @(Get-ChildItem -LiteralPath "$PSScriptRoot\wheels" -Filter '*.whl' | ForEach-Object FullName)
& $python -m pip install --no-cache-dir --disable-pip-version-check --no-input @wheels
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
Copy-Item -LiteralPath "$PSScriptRoot\manifest.json" -Destination $Destination
$entry = if ($manifest.project -eq 'webui') { 'from open_webui import app; app()' } else { 'from open_terminal.cli import main; main()' }
$launch = @('@echo off', 'setlocal', 'cd /d "%~dp0"', 'if not exist data mkdir data', 'set "DATA_DIR=%~dp0data"', 'set "HF_HOME=%~dp0models"', ('"%~dp0python\python.exe" -c "' + $entry + '" ' + $(if ($manifest.project -eq 'webui') { 'serve --host 127.0.0.1 --port 8080' } else { 'run --host 127.0.0.1 --port 8000' })), 'exit /b %errorlevel%')
[IO.File]::WriteAllLines((Join-Path $Destination 'Start.cmd'), $launch, [Text.Encoding]::ASCII)
Write-Output "Installed. Launch $Destination\Start.cmd. Models download on demand from Hugging Face."
