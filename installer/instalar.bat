@echo off
rem Instala el add-in Voladizos FDM (FDMOverhang) en Fusion 360 copiando la carpeta FDMOverhang
rem a la carpeta de complementos del usuario. No hace falta ser administrador.
chcp 65001 >nul
setlocal
set "SRC=%~dp0FDMOverhang"
set "ADDINS=%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns"
set "DST=%ADDINS%\FDMOverhang"

if not exist "%SRC%\FDMOverhang.py" (
    echo No encuentro la carpeta FDMOverhang junto a este archivo. Descomprime el zip entero antes de instalar.
    echo The FDMOverhang folder is not next to this file. Unzip the whole zip before installing.
    goto :fin
)
if not exist "%ADDINS%" (
    echo No encuentro la carpeta de complementos de Fusion 360:
    echo   %ADDINS%
    echo Abre Fusion 360 al menos una vez y vuelve a probar.
    echo The Fusion 360 add-ins folder was not found: open Fusion 360 once and try again.
    goto :fin
)
rem Si es un enlace al repo (instalación de desarrollo), no se toca
dir /AL /B "%ADDINS%" 2>nul | findstr /X /I "FDMOverhang" >nul
if not errorlevel 1 (
    echo %DST% es un enlace a otra carpeta, no lo sobrescribo.
    echo %DST% is a link to another folder, not overwriting it.
    goto :fin
)

rem Copia espejo: borra lo que ya no existe, pero conserva los últimos valores del diálogo
robocopy "%SRC%" "%DST%" /MIR /XF settings.json /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
    echo Ha fallado la copia a %DST%.
    echo Si Fusion está abierto, ciérralo y vuelve a probar.
    echo Copy to %DST% failed. If Fusion is open, close it and try again.
    goto :fin
)

echo Instalado en:
echo   %DST%
echo.
echo En Fusion 360: Utilidades ^> Complementos (Mayús+S) ^> FDMOverhang ^> Ejecutar,
echo y marca "Al iniciar". Si Fusion ya estaba abierto y tenías una versión anterior,
echo detén el complemento y vuelve a ejecutarlo.
echo El botón está en DISEÑO ^> INSPECCIONAR ^> Voladizos FDM.
echo.
echo Installed. In Fusion 360: Utilities ^> Add-Ins (Shift+S) ^> FDMOverhang ^> Run,
echo and tick "Run on Startup". If Fusion was already open with an earlier version,
echo stop the add-in and run it again.
echo The button is in DESIGN ^> INSPECT ^> FDM overhangs.

:fin
echo.
pause
