# Captura solo la ventana de un proceso, sin el resto del escritorio.
param([string]$ProcessName, [string]$OutFile, [int]$TimeoutSeconds = 90, [string]$TitleMatch = '.')
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System; using System.Runtime.InteropServices;
public static class Win32Capture {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);
}
'@
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$target = $null
while ((Get-Date) -lt $deadline) {
    $target = Get-Process -Name $ProcessName -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle -match $TitleMatch } |
        Select-Object -First 1
    if ($target) { break }
    Start-Sleep -Seconds 2
}
if (-not $target) { Write-Output "Sin ventana de $ProcessName"; exit 1 }
# Deja que termine de cargar el proyecto y dibuje la vista.
Start-Sleep -Seconds 12
$target.Refresh()
Write-Output "Título: $($target.MainWindowTitle)"
$rect = New-Object Win32Capture+RECT
[void][Win32Capture]::GetWindowRect($target.MainWindowHandle, [ref]$rect)
$bmp = New-Object System.Drawing.Bitmap ($rect.R - $rect.L), ($rect.B - $rect.T)
$gfx = [System.Drawing.Graphics]::FromImage($bmp)
$hdc = $gfx.GetHdc()
[void][Win32Capture]::PrintWindow($target.MainWindowHandle, $hdc, 2)
$gfx.ReleaseHdc($hdc)
$bmp.Save($OutFile, [System.Drawing.Imaging.ImageFormat]::Png)
$gfx.Dispose(); $bmp.Dispose()
Write-Output "Guardado: $OutFile"
