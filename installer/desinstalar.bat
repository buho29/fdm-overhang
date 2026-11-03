@echo off
rem Quita el add-in Voladizos FDM (FDMOverhang) de la carpeta de complementos de Fusion 360.
chcp 65001 >nul
setlocal
set "ADDINS=%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns"
set "DST=%ADDINS%\FDMOverhang"

if not exist "%DST%" (
    echo FDMOverhang no está instalado en %ADDINS%.
    echo FDMOverhang is not installed in %ADDINS%.
    goto :fin
)
rem Un enlace al repo (instalación de desarrollo) no se borra desde aquí
dir /AL /B "%ADDINS%" 2>nul | findstr /X /I "FDMOverhang" >nul
if not errorlevel 1 (
    echo %DST% es un enlace a otra carpeta, no lo borro.
    echo %DST% is a link to another folder, not deleting it.
    goto :fin
)

echo Antes de seguir, detén el complemento en Fusion (Utilidades ^> Complementos ^> FDMOverhang ^> Detener)
echo o cierra Fusion.
echo First stop the add-in in Fusion (Utilities ^> Add-Ins ^> FDMOverhang ^> Stop) or close Fusion.
pause
rmdir /S /Q "%DST%"
if exist "%DST%" (
    echo No se ha podido borrar del todo %DST%. Cierra Fusion y vuelve a probar.
    echo %DST% could not be fully deleted. Close Fusion and try again.
) else (
    echo Voladizos FDM desinstalado. / FDM overhangs uninstalled.
)

:fin
echo.
pause
