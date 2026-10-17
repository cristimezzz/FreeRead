<#
.SYNOPSIS
  用 PyInstaller 把 core 打包成 Tauri sidecar（不含 PDF 解析引擎）。

.DESCRIPTION
  1. 用 uv 在 build/sidecar/.venv 建独立的 Python 3.12 环境，安装 core 基础依赖和 PyInstaller
     （PyInstaller 只装在这个构建环境里，不写进 core/pyproject.toml）。
  2. --onefile 打包，按 Rust target triple 命名为 freeread-core-<triple>.exe，
     复制到 apps/desktop/src-tauri/binaries/ 供 tauri.conf.json 的 externalBin 使用。
  3. 另打一份 --onedir 到 build/sidecar/dist-onedir/，用来对比启动时间（-SkipOnedir 跳过）。

.EXAMPLE
  pwsh scripts/build_sidecar.ps1
#>
param(
    [string]$PythonVersion = "3.12",
    [switch]$SkipOnedir
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Core = Join-Path $Root "core"
$Build = Join-Path $Root "build/sidecar"
$Venv = Join-Path $Build ".venv"
$Python = Join-Path $Venv "Scripts/python.exe"
$Binaries = Join-Path $Root "apps/desktop/src-tauri/binaries"

New-Item -ItemType Directory -Force $Build, $Binaries | Out-Null

Write-Host "==> Python $PythonVersion 构建环境：$Venv"
if (-not (Test-Path $Python)) {
    uv venv $Venv --python $PythonVersion
}
uv pip install --python $Python $Core "pyinstaller>=6.10"

# PyInstaller 入口：直接用包内模块作脚本会丢失包上下文，这里生成一个最小入口。
$Entry = Join-Path $Build "freeread_core_entry.py"
Set-Content -Encoding utf8 $Entry @"
from freeread.main import run

if __name__ == "__main__":
    run()
"@

$Triple = (rustc -vV | Select-String "^host: (.+)$").Matches[0].Groups[1].Value
Write-Host "==> target triple: $Triple"

# uvicorn 按字符串动态加载 loop / protocol 实现，需要显式收集。
# Alembic 按文件路径加载迁移脚本（env.py、versions/*.py），要以源文件形式带上。
$Migrations = Join-Path $Core "freeread/infra/db/migrations"
$Common = @(
    "--noconfirm", "--clean", "--console",
    "--name", "freeread-core",
    "--collect-submodules", "uvicorn",
    "--add-data", "${Migrations};freeread/infra/db/migrations",
    "--workpath", (Join-Path $Build "work"),
    "--specpath", $Build,
    $Entry
)

Write-Host "==> PyInstaller --onefile"
& $Python -m PyInstaller --onefile --distpath (Join-Path $Build "dist-onefile") @Common
$OneFile = Join-Path $Build "dist-onefile/freeread-core.exe"
$Target = Join-Path $Binaries "freeread-core-$Triple.exe"
Copy-Item -Force $OneFile $Target
Write-Host ("    {0} ({1:N1} MB)" -f $Target, ((Get-Item $Target).Length / 1MB))

if (-not $SkipOnedir) {
    Write-Host "==> PyInstaller --onedir"
    & $Python -m PyInstaller --onedir --distpath (Join-Path $Build "dist-onedir") @Common
    $OneDir = Join-Path $Build "dist-onedir/freeread-core"
    $Size = (Get-ChildItem -Recurse -File $OneDir | Measure-Object Length -Sum).Sum
    Write-Host ("    {0} ({1:N1} MB)" -f $OneDir, ($Size / 1MB))
}
