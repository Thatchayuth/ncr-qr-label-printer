# Publish a built installer to the update folder, so installed copies offer the update.
#
#   .\scripts\publish_update.ps1 -Notes "Fix grade box on the STOCK label"
#   .\scripts\publish_update.ps1 -Folder \\server\share\NCRPrintLabel -Required
#
# Copies dist\installer\NCR-Print-Label-Setup-<version>.exe to the folder and then writes latest.json
# (version, file, SHA-256, notes, required). latest.json is written last, so programs never see a
# version whose installer is not completely copied yet. Refuses to publish an older or equal version
# unless -Force is given.
param(
    [string]$Folder = '\\ncr230\RY_File\_Free-OSS\NCRPrintLabel',
    [string]$Notes = '',
    [switch]$Required,
    [switch]$Force
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root '.venv\Scripts\python.exe'

$version = (& $py -c "import sys; sys.path.insert(0, r'$root\src'); from qrlabel import __version__; print(__version__)").Trim()
$file = "NCR-Print-Label-Setup-$version.exe"
$installer = Join-Path $root "dist\installer\$file"
if (-not (Test-Path -LiteralPath $installer)) { throw "Build the installer first (scripts\build.ps1): $installer not found." }

if (-not (Test-Path -LiteralPath $Folder)) {
    New-Item -ItemType Directory -Path $Folder | Out-Null
    Write-Host "Created $Folder"
}
$manifest = Join-Path $Folder 'latest.json'
if ((Test-Path -LiteralPath $manifest) -and -not $Force) {
    $current = (Get-Content -LiteralPath $manifest -Raw -Encoding UTF8 | ConvertFrom-Json).version
    if ([version]$current -ge [version]$version) {
        throw "The folder already offers version $current. Raise __version__ in src\qrlabel\__init__.py, rebuild, or use -Force."
    }
}

Write-Host "Copying $file ..."
Copy-Item -LiteralPath $installer -Destination (Join-Path $Folder $file) -Force
$hash = (Get-FileHash -LiteralPath (Join-Path $Folder $file) -Algorithm SHA256).Hash.ToLower()
$local = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLower()
if ($hash -ne $local) { throw "The copy in the folder differs from the built installer. Try again." }

$data = [ordered]@{
    version   = $version
    file      = $file
    sha256    = $hash
    notes     = $Notes
    required  = [bool]$Required
    published = (Get-Date -Format 'yyyy-MM-dd HH:mm')
    by        = "$env:USERDOMAIN\$env:USERNAME"
}
$json = $data | ConvertTo-Json
# Written in place (not temp file + rename): the share may allow writing but not deleting or renaming
# files, as for ICT-RY on \\ncr230\RY_File. latest.json is still written only after the installer is
# copied and verified, and it is small enough to be written in one go.
[System.IO.File]::WriteAllText($manifest, $json, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "Published version $version to $Folder" -ForegroundColor Green
Write-Host $json
