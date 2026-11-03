# Registra esta carpeta en la lista de complementos de Fusion 360 con su ruta real, como el botón "+" del
# diálogo de complementos, y con "Ejecutar al inicio". Fusion carga directamente lo que hay en el repo.
# Hay que cerrar Fusion antes: guarda su lista al salir y pisaría el cambio.
# Uso:  powershell -ExecutionPolicy Bypass -File install.ps1
$fusionDir = Join-Path $env:APPDATA 'Autodesk\Autodesk Fusion 360'
$script = (Join-Path $PSScriptRoot 'FDMOverhang.py') -replace '\\', '/'

if (Get-Process Fusion360 -ErrorAction SilentlyContinue) {
    Write-Error 'Cierra Fusion antes de ejecutar este script.'
    exit 1
}

# La lista de complementos está en una carpeta por usuario de Autodesk
$lists = @(Get-ChildItem $fusionDir -Directory -ErrorAction SilentlyContinue |
    ForEach-Object { Join-Path $_.FullName 'JSLoadedScriptsinfo' } | Where-Object { Test-Path $_ })
if (-not $lists) {
    Write-Error "No encuentro la lista de complementos de Fusion en $fusionDir. Abre Fusion una vez, ciérralo y repite."
    exit 1
}

foreach ($list in $lists) {
    Copy-Item $list "$list.bak" -Force
    $data = Get-Content $list -Raw -Encoding UTF8 | ConvertFrom-Json
    $old = @($data.loadedScripts | Where-Object { $_.path -eq $script })
    $data.loadedScripts = @($data.loadedScripts | Where-Object { $_.path -ne $script }) + [pscustomobject]@{
        name = 'FDMOverhang'
        path = $script
        location = 3
        isRemoved = $false
        isFavorite = [bool]($old | Where-Object { $_.isFavorite })
        runOnStartup = $true
    }
    [IO.File]::WriteAllText($list, ($data | ConvertTo-Json -Depth 5))
    Write-Host "Registrado en $list -> $script (copia en $list.bak)"
}
Write-Host 'Al abrir Fusion, Voladizos FDM arranca solo (INSPECCIONAR > Voladizos FDM). Para pararlo o quitarlo: Utilidades > Complementos (Mayús+S).'
