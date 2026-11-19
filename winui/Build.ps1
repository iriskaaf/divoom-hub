param(
    [string]$PythonRoot = '',
    [string]$Destination = (Join-Path $PSScriptRoot 'artifacts/DivoomHub.WinUI'),
    [string]$TestDestination = (Join-Path $PSScriptRoot 'artifacts/test'),
    [ValidateSet('Debug', 'Release')][string]$Configuration = 'Release'
)
$ErrorActionPreference = 'Stop'
if (!$PythonRoot) {
    $PythonRoot = Join-Path (Split-Path $PSScriptRoot) 'legacy'
    if (!(Test-Path (Join-Path $PythonRoot 'core/player.py'))) {
        $PythonRoot = Join-Path (Split-Path (Split-Path $PSScriptRoot)) 'VSC/DIVOOM_SPOTIFY'
    }
}
$env:DIVOOM_HUB_PYTHON_ROOT = (Resolve-Path -LiteralPath $PythonRoot).Path
$runtime = Join-Path $env:DIVOOM_HUB_PYTHON_ROOT '.venv/Scripts/python.exe'
$project = Join-Path $PSScriptRoot 'divoom-hub-winui3.csproj'
$spec = Join-Path $PSScriptRoot 'Backend/DivoomHub.Backend.spec'
$pythonBuild = Join-Path $PSScriptRoot 'obj/python-backend'
$destinationPath = [IO.Path]::GetFullPath($Destination)
if ((Get-Process 'divoom-hub-winui3' -ErrorAction SilentlyContinue).Path -contains (Join-Path $destinationPath 'divoom-hub-winui3.exe')) {
    throw 'Exit the copy being rebuilt from the tray.'
}
$testPath = [IO.Path]::GetFullPath($TestDestination)
if ($testPath -eq $destinationPath) { throw 'TEST and production require separate output directories.' }
if ((Get-Process 'divoom-hub-winui3_TEST' -ErrorAction SilentlyContinue).Path -contains (Join-Path $testPath 'divoom-hub-winui3_TEST.exe')) {
    throw 'Exit TEST from the tray before rebuilding.'
}
& $runtime -m PyInstaller --noconfirm --workpath (Join-Path $pythonBuild 'work') --distpath (Join-Path $pythonBuild 'dist') $spec
if ($LASTEXITCODE) { throw 'Python backend build failed.' }
dotnet publish $project -c $Configuration -r win-x64 -p:Platform=x64 -p:WindowsPackageType=None -p:WindowsAppSDKSelfContained=true -p:PublishTrimmed=false -p:PublishReadyToRun=false --self-contained true -o $destinationPath
if ($LASTEXITCODE) { throw 'WinUI publish failed.' }
$backend = Join-Path $destinationPath 'Backend'
Copy-Item -Path (Join-Path $pythonBuild 'dist/DivoomHub.Backend/*') -Destination $backend -Recurse -Force
New-Item -ItemType Directory -Path $testPath -Force | Out-Null
Get-ChildItem -LiteralPath $destinationPath | Where-Object Name -ne 'divoom-hub-winui3.exe' |
    Copy-Item -Destination $testPath -Recurse -Force
Copy-Item -LiteralPath (Join-Path $destinationPath 'divoom-hub-winui3.exe') -Destination (Join-Path $testPath 'divoom-hub-winui3_TEST.exe') -Force
# The unpackaged XAML loader resolves the primary resource index by executable name.
Copy-Item -LiteralPath (Join-Path $destinationPath 'divoom-hub-winui3.pri') -Destination (Join-Path $testPath 'divoom-hub-winui3_TEST.pri') -Force
Write-Output (Join-Path $destinationPath 'divoom-hub-winui3.exe')
Write-Output (Join-Path $testPath 'divoom-hub-winui3_TEST.exe')
