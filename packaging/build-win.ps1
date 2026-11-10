# Coldshift Dash for Windows, built on this PC: dist\Coldshift-Dash-<version>-win-<arch>.zip
#
#   powershell -ExecutionPolicy Bypass -File packaging\build-win.ps1
#
# Needs Python 3.11 or newer on the PATH ($env:PYTHON to choose one; the app is for that Python's architecture).
# The folder is not signed: Windows SmartScreen warns about it until it is signed with a code-signing certificate.
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktop = Split-Path -Parent $here
$py = if ($env:PYTHON) { $env:PYTHON } else { "python" }
$version = (Select-String -Path "$desktop\dashsync\__init__.py" -Pattern '^VERSION = "(.*)"').Matches[0].Groups[1].Value
$arch = (& $py -c "import platform; print(platform.machine().lower())")
$out = "$here\dist"
$work = "$here\build"
$venv = "$here\.venv"

Write-Host "== Coldshift Dash $version for Windows ($arch)"
if (-not (Test-Path "$venv\Scripts\python.exe")) { & $py -m venv $venv }
& "$venv\Scripts\python.exe" -m pip install -q --upgrade -r "$desktop\requirements.txt" "pyinstaller>=6.16"
if ($LASTEXITCODE -ne 0) { throw "pip failed" }

# what Explorer shows under Properties > Details
if (Test-Path $work) { Remove-Item -Recurse -Force $work }
New-Item -ItemType Directory -Force $work | Out-Null
$parts = ($version.Split(".") + @("0", "0", "0", "0"))[0..3] -join ", "
@"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($parts), prodvers=($parts), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'The Future is Now-Now (PTY) Ltd'),
      StringStruct('FileDescription', 'Coldshift Dash'),
      StringStruct('FileVersion', '$version'),
      StringStruct('InternalName', 'Coldshift Dash'),
      StringStruct('LegalCopyright', 'The Future is Now-Now (PTY) Ltd'),
      StringStruct('OriginalFilename', 'Coldshift Dash.exe'),
      StringStruct('ProductName', 'Coldshift Dash'),
      StringStruct('ProductVersion', '$version')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"@ | Set-Content -Encoding UTF8 "$work\version-info.txt"

if (Test-Path $out) { Remove-Item -Recurse -Force $out }
$env:APP_VERSION = $version
& "$venv\Scripts\pyinstaller.exe" --noconfirm --log-level WARN --distpath $out --workpath "$work\pyinstaller" "$here\coldshift-dash.spec"
if ($LASTEXITCODE -ne 0) { throw "pyinstaller failed" }

$zip = "$out\Coldshift-Dash-$version-win-$arch.zip"
Compress-Archive -Path "$out\Coldshift Dash" -DestinationPath $zip
Write-Host $zip
(Get-FileHash -Algorithm SHA256 $zip).Hash
