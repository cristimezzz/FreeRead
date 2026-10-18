<#
.SYNOPSIS
  用 PyInstaller 把 core 打包成 Tauri sidecar（不含重型 PDF 解析引擎）。

.DESCRIPTION
  1. 用 uv 在 build/sidecar/.venv 建独立的 Python 3.12 环境，安装 core 基础依赖和 PyInstaller
     （PyInstaller 只装在这个构建环境里，不写进 core/pyproject.toml）。
  2. --onedir 打包到 build/sidecar/dist/freeread-core/，再整个目录复制到
     apps/desktop/src-tauri/binaries/freeread-core/，由 tauri.conf.json 的 bundle.resources
     安装到 <resource_dir>/freeread-core/，壳从那里启动 freeread-core.exe（apps/desktop/src-tauri/src/lib.rs）。
     不用 externalBin：它只能带单个可执行文件，onedir 的 _internal/ 带不上。
     选 onedir 而不是 onefile 的原因见 docs/m0-tauri-sidecar.md（热启动快约 2 s，且不往 %TEMP% 解压）。
  3. 一起打进去的数据文件：Alembic 迁移脚本（按文件路径加载）和 core/prompts/*.yaml。

.EXAMPLE
  pwsh scripts/build_sidecar.ps1
#>
param(
    [string]$PythonVersion = "3.12"
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Core = Join-Path $Root "core"
$Build = Join-Path $Root "build/sidecar"
$Venv = Join-Path $Build ".venv"
$Python = Join-Path $Venv "Scripts/python.exe"
$Target = Join-Path $Root "apps/desktop/src-tauri/binaries/freeread-core"

New-Item -ItemType Directory -Force $Build | Out-Null

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

# uvicorn 按字符串动态加载 loop / protocol 实现，需要显式收集。
# Alembic 按文件路径加载迁移脚本（env.py、versions/*.py），要以源文件形式带上；
# 迁移脚本里 import 的 alembic.op / sqlalchemy 方言也要收集（静态分析看不到）。
# 提示词放在包外的 prompts/，运行时从 sys._MEIPASS/prompts 读（freeread/infra/llm/prompts.py）。
$Migrations = Join-Path $Core "freeread/infra/db/migrations"
$Prompts = Join-Path $Core "prompts"
$Dist = Join-Path $Build "dist"

Write-Host "==> PyInstaller --onedir"
& $Python -m PyInstaller --onedir --noconfirm --clean --console `
    --name freeread-core `
    --collect-submodules uvicorn `
    --collect-submodules alembic `
    --hidden-import sqlalchemy.dialects.sqlite `
    --add-data "${Migrations};freeread/infra/db/migrations" `
    --add-data "${Prompts};prompts" `
    --distpath $Dist `
    --workpath (Join-Path $Build "work") `
    --specpath $Build `
    $Entry

$OneDir = Join-Path $Dist "freeread-core"
foreach ($required in @(
        "freeread-core.exe",
        "_internal/freeread/infra/db/migrations/env.py",
        "_internal/prompts/translate.yaml"
    )) {
    if (-not (Test-Path (Join-Path $OneDir $required))) {
        throw "onedir 产物缺少 $required"
    }
}

if (Test-Path $Target) {
    Remove-Item -Recurse -Force $Target
}
New-Item -ItemType Directory -Force (Split-Path $Target) | Out-Null
Copy-Item -Recurse $OneDir $Target
$Files = Get-ChildItem -Recurse -File $Target
Write-Host ("    {0}（{1} 个文件，{2:N1} MB）" -f $Target, $Files.Count, (($Files | Measure-Object Length -Sum).Sum / 1MB))
