# Builds the stand-alone Windows version: dist\nightride\nightride.exe, with Python and VLC included,
# dist\nightride-windows.zip of that folder, and the installer dist\nightride-setup.exe of it if
# Inno Setup 6 (https://jrsoftware.org/isinfo.php) is installed.
#
# Run in PowerShell from anywhere:
#     powershell -ExecutionPolicy Bypass -File windows\build.ps1
#
# Needs uv (https://docs.astral.sh/uv/) or 64-bit Python 3.9+ on the PATH, and internet access.

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"  # Invoke-WebRequest is very slow with the progress bar

$VlcVersion = "3.0.24"
$VlcSha256 = "fcf30850371ad10c9373cc4f0f4501e7dee49e3e9ae9f20c72fb2661a1ca6323"
# The VLC plugin folders needed to play an internet radio stream. The rest (video, GUI, streaming
# out, ...) would only make the download bigger.
$VlcPlugins = @(
    "access", "audio_filter", "audio_mixer", "audio_output", "codec", "demux",
    "keystore", "logger", "misc", "packetizer", "stream_extractor", "stream_filter"
)

$Root = Split-Path -Parent $PSScriptRoot
$Build = Join-Path $Root "build"
$Dist = Join-Path $Root "dist"
Set-Location $Root
New-Item -ItemType Directory -Force $Build | Out-Null

### VLC ###

$VlcZip = Join-Path $Build "vlc-$VlcVersion-win64.zip"
if (-not (Test-Path $VlcZip)) {
    Write-Host "Downloading VLC $VlcVersion"
    $url = "https://download.videolan.org/pub/videolan/vlc/$VlcVersion/win64/vlc-$VlcVersion-win64.zip"
    Invoke-WebRequest $url -OutFile "$VlcZip.part"
    Move-Item -Force "$VlcZip.part" $VlcZip
}
$hash = (Get-FileHash -Algorithm SHA256 $VlcZip).Hash.ToLower()
if ($hash -ne $VlcSha256) {
    Remove-Item $VlcZip
    throw "VLC download has the wrong checksum ($hash). Deleted it, try again."
}

$VlcUnpacked = Join-Path $Build "vlc-unpacked"
$Vlc = Join-Path $Build "vlc"
Remove-Item -Recurse -Force $VlcUnpacked, $Vlc -ErrorAction SilentlyContinue
Expand-Archive $VlcZip $VlcUnpacked
$VlcSource = Join-Path $VlcUnpacked "vlc-$VlcVersion"

New-Item -ItemType Directory -Force (Join-Path $Vlc "plugins") | Out-Null
Copy-Item (Join-Path $VlcSource "libvlc.dll"), (Join-Path $VlcSource "libvlccore.dll") $Vlc
Copy-Item (Join-Path $VlcSource "COPYING.txt") (Join-Path $Vlc "VLC-COPYING.txt")
foreach ($plugin in $VlcPlugins) {
    Copy-Item -Recurse (Join-Path $VlcSource "plugins\$plugin") (Join-Path $Vlc "plugins")
}
# A fresh plugin cache for the plugins we kept, so VLC starts fast
& (Join-Path $VlcSource "vlc-cache-gen.exe") (Join-Path $Vlc "plugins")
if ($LASTEXITCODE -ne 0) { throw "vlc-cache-gen failed" }

### Python ###

$Venv = Join-Path $Build "venv"
if (Get-Command uv -ErrorAction SilentlyContinue) {
    uv venv --allow-existing --python 3.12 $Venv
    if ($LASTEXITCODE -ne 0) { throw "uv venv failed" }
    $env:VIRTUAL_ENV = $Venv
    uv pip install -r requirements.txt "pyinstaller>=6.11,<7"
} else {
    python -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create a virtual environment. Is Python installed?" }
    & (Join-Path $Venv "Scripts\python.exe") -m pip install -r requirements.txt "pyinstaller>=6.11,<7"
}
if ($LASTEXITCODE -ne 0) { throw "Installing the Python packages failed" }

$bits = & (Join-Path $Venv "Scripts\python.exe") -c "import struct; print(struct.calcsize('P') * 8)"
if ($bits -ne "64") { throw "Python is $bits-bit, but the bundled VLC is 64-bit. Use 64-bit Python." }

### Build ###

& (Join-Path $Venv "Scripts\pyinstaller.exe") --noconfirm --clean `
    --distpath $Dist --workpath (Join-Path $Build "pyinstaller") `
    (Join-Path $PSScriptRoot "nightride.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$App = Join-Path $Dist "nightride"
Copy-Item README.md, LICENSE, MANUAL.txt $App
Copy-Item (Join-Path $PSScriptRoot "README-windows.txt") (Join-Path $App "README.txt")

$Zip = Join-Path $Dist "nightride-windows.zip"
Remove-Item -Force $Zip -ErrorAction SilentlyContinue
Compress-Archive $App $Zip

### Installer ###

$Setup = Join-Path $Dist "nightride-setup.exe"
Remove-Item -Force $Setup -ErrorAction SilentlyContinue
$Iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
if (-not $Iscc) {
    $Iscc = Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"
}
if (Test-Path $Iscc) {
    $Version = (Select-String -Path pyproject.toml -Pattern '^version = "(.+)"').Matches[0].Groups[1].Value
    & $Iscc /Q "/DAppVersion=$Version" (Join-Path $PSScriptRoot "nightride.iss")
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
} else {
    Write-Host "Inno Setup 6 not found, so no installer"
    $Setup = $null
}

Write-Host ""
Write-Host "Done: $App\nightride.exe"
Write-Host "      $Zip"
if ($Setup) { Write-Host "      $Setup" }
