# Genera dist\FDMOverhang-<versión>.zip para instalar el add-in sin el repo.
# El zip lleva instalar.bat, desinstalar.bat, LEEME.txt, README.txt y la carpeta FDMOverhang con solo lo que
# necesita Fusion (y la licencia y los README).
# Uso:  powershell -ExecutionPolicy Bypass -File installer\make_release.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$version = [regex]::Match((Get-Content (Join-Path $root 'FDMOverhang.manifest') -Raw), '"version"\s*:\s*"([^"]+)"').Groups[1].Value
$dist = Join-Path $root 'dist'
$stage = Join-Path $dist 'stage'
$addin = Join-Path $stage 'FDMOverhang'
$zip = Join-Path $dist "FDMOverhang-$version.zip"

if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
foreach ($d in 'overhang', 'resources', 'resources\thickness', 'img') { New-Item -ItemType Directory -Force (Join-Path $addin $d) | Out-Null }

# Lo que carga Fusion (sin settings.json, __pycache__, pruebas, install.ps1 ni este instalador)
Copy-Item (Join-Path $root 'FDMOverhang.manifest'), (Join-Path $root 'FDMOverhang.py'), (Join-Path $root 'LICENSE'),
          (Join-Path $root 'README.md'), (Join-Path $root 'README.en.md') $addin
Copy-Item (Join-Path $root 'overhang\*.py') (Join-Path $addin 'overhang')
Copy-Item (Join-Path $root 'resources\*.png') (Join-Path $addin 'resources')
Copy-Item (Join-Path $root 'resources\thickness\*.png') (Join-Path $addin 'resources\thickness')
Copy-Item (Join-Path $root 'img\*.png') (Join-Path $addin 'img')   # las imágenes de los README
Copy-Item (Join-Path $PSScriptRoot 'instalar.bat'), (Join-Path $PSScriptRoot 'desinstalar.bat'),
          (Join-Path $PSScriptRoot 'LEEME.txt'), (Join-Path $PSScriptRoot 'README.txt') $stage

if (Test-Path $zip) { Remove-Item $zip -Force }
# Entradas a mano con '/': Compress-Archive y CreateFromDirectory de PowerShell 5 guardan '\' y en Mac no se descomprime bien
Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
$archive = [IO.Compression.ZipFile]::Open($zip, 'Create')
try {
    Get-ChildItem $stage -Recurse -File | ForEach-Object {
        $name = $_.FullName.Substring($stage.Length + 1).Replace('\', '/')
        [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $_.FullName, $name) | Out-Null
    }
} finally { $archive.Dispose() }
Remove-Item $stage -Recurse -Force
Write-Host "Creado: $zip"
