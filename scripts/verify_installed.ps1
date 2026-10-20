<#
.SYNOPSIS
  安装 NSIS 包并复测体积、启动时间、退出残留（方法见 docs/m0-tauri-sidecar.md），输出 Markdown。

.DESCRIPTION
  1. 静默安装（/S，可用 -InstallDir 指定目录），记录安装包大小、安装耗时、安装后目录大小；
  2. scripts/measure_sidecar.ps1 对已安装的 sidecar 测冷 / 热启动（每次新数据目录，含迁移）；
  3. 启动壳 freeread-desktop.exe：从 sidecar 命令行取端口和 token，计时到 /health 可用，
     检查数据目录（%APPDATA%\FreeRead）里数据库已创建；
  4. 退出清理：正常关闭窗口（CloseMainWindow）和 taskkill /F 壳各 -Runs 次，
     每 50 ms 检查一次 freeread-core 进程，最多等 15 s。
  需要交互的检查（文件对话框、钥匙串、阅读器）不在这里，见 docs/m1/README.md。

.EXAMPLE
  pwsh scripts/verify_installed.ps1 -Installer apps/desktop/src-tauri/target/release/bundle/nsis/FreeRead_0.0.1_x64-setup.exe
#>
param(
    [Parameter(Mandatory)][string]$Installer,
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "FreeRead"),
    [int]$Runs = 5,
    [string]$Out = "verify-installed.md"
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Net.Http
$lines = [Collections.Generic.List[string]]::new()
function Emit([string]$s) { Write-Host $s; $lines.Add($s) }
function Get-CoreProcs { @(Get-CimInstance Win32_Process -Filter "Name='freeread-core.exe'") }

$Installer = (Resolve-Path $Installer).Path
Emit "# 安装包复测（$(Get-Date -Format 'yyyy-MM-dd HH:mm')，$env:COMPUTERNAME）"
Emit ""
Emit ("- 安装包：{0}（{1:N2} MiB，{2:N0} 字节）" -f (Split-Path -Leaf $Installer), ((Get-Item $Installer).Length / 1MB), (Get-Item $Installer).Length)

# 1. 静默安装
$sw = [Diagnostics.Stopwatch]::StartNew()
$proc = Start-Process -PassThru -Wait $Installer -ArgumentList "/S", "/D=$InstallDir"
$installMs = $sw.ElapsedMilliseconds
$shell = Join-Path $InstallDir "freeread-desktop.exe"
$coreDir = Join-Path $InstallDir "freeread-core"
if (-not (Test-Path $shell) -or -not (Test-Path (Join-Path $coreDir "freeread-core.exe"))) {
    throw "安装失败：$InstallDir 下没有 freeread-desktop.exe / freeread-core\freeread-core.exe（安装程序退出码 $($proc.ExitCode)）"
}
$files = Get-ChildItem -Recurse -File $InstallDir
Emit ("- 静默安装耗时：{0:N1} s；安装后目录：{1:N1} MB，{2} 个文件" -f ($installMs / 1000), (($files | Measure-Object Length -Sum).Sum / 1MB), $files.Count)
$coreFiles = Get-ChildItem -Recurse -File $coreDir
Emit ("- 其中 sidecar onedir：{0:N1} MB；壳 exe：{1:N1} MB" -f (($coreFiles | Measure-Object Length -Sum).Sum / 1MB), ((Get-Item $shell).Length / 1MB))
foreach ($f in "_internal\prompts\translate.yaml", "_internal\freeread\infra\db\migrations\env.py") {
    if (-not (Test-Path (Join-Path $coreDir $f))) { throw "安装目录缺少 $f" }
}
Emit ""

# 2. sidecar 冷 / 热启动
Emit "## sidecar 启动到 /health（ms，每次新数据目录，含迁移）"
Emit ""
foreach ($mode in "cold", "warm") {
    $out = @(& pwsh -NoProfile -File (Join-Path $PSScriptRoot "measure_sidecar.ps1") -Mode $mode -Runs $Runs -Dir $coreDir 2>&1)
    # 子进程里的异常不会传上来：看退出码，冒烟失败（导入 / 解析 / 检索）时打出全部输出（含 sidecar 日志）并失败
    if ($LASTEXITCODE) {
        $out | ForEach-Object { Write-Host $_ }
        throw "sidecar 复测失败（$mode），见上面的 freeread-core 日志"
    }
    Emit "- $($out[-1])"
}
Emit ""

# 3. 壳启动
function Start-Shell {
    $before = Get-CoreProcs | ForEach-Object ProcessId
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $p = Start-Process -PassThru $shell
    $core = $null
    while (-not $core) {
        if ($sw.Elapsed.TotalSeconds -gt 30) { throw "30 s 内没有看到 freeread-core 进程" }
        if ($p.HasExited) { throw "壳提前退出（$($p.ExitCode)）" }
        $core = Get-CoreProcs | Where-Object { $_.ParentProcessId -eq $p.Id -and $before -notcontains $_.ProcessId } | Select-Object -First 1
        Start-Sleep -Milliseconds 20
    }
    if ($core.CommandLine -notmatch "--port (\d+) --token (\w+)") { throw "无法从命令行解析端口：$($core.CommandLine)" }
    $port = $Matches[1]
    $client = [Net.Http.HttpClient]::new()
    $client.Timeout = [TimeSpan]::FromSeconds(2)
    $client.DefaultRequestHeaders.Add("X-FreeRead-Token", $Matches[2])
    try {
        while ($true) {
            if ($sw.Elapsed.TotalSeconds -gt 60) { throw "60 s 内 /health 不可用" }
            try {
                if ($client.GetAsync("http://127.0.0.1:$port/health").GetAwaiter().GetResult().IsSuccessStatusCode) { break }
            } catch { }
            Start-Sleep -Milliseconds 20
        }
    } finally { $client.Dispose() }
    [pscustomobject]@{ Shell = $p; Ms = $sw.ElapsedMilliseconds }
}

function Wait-NoCore {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ((Get-CoreProcs).Count -gt 0) {
        if ($sw.Elapsed.TotalSeconds -gt 15) { return $null }
        Start-Sleep -Milliseconds 50
    }
    $sw.ElapsedMilliseconds
}

Emit "## 壳启动 → /health 可用 与 退出清理"
Emit ""
if ((Get-CoreProcs).Count -gt 0) { throw "开始前已有 freeread-core 进程在运行" }
$dataDb = Join-Path $env:APPDATA "FreeRead\freeread.db"
$startMs = @()
foreach ($how in "close", "kill") {
    $cleanup = @()
    foreach ($i in 1..$Runs) {
        $r = Start-Shell
        $startMs += $r.Ms
        Start-Sleep -Seconds 1
        if ($how -eq "close") {
            # 等同于点击关闭按钮；窗口句柄可能稍晚才出现
            $deadline = (Get-Date).AddSeconds(10)
            while (-not $r.Shell.CloseMainWindow()) {
                if ((Get-Date) -gt $deadline) { throw "找不到主窗口" }
                Start-Sleep -Milliseconds 200
                $r.Shell.Refresh()
            }
        } else {
            taskkill /F /PID $r.Shell.Id | Out-Null
        }
        $ms = Wait-NoCore
        $cleanup += if ($null -eq $ms) { "残留" } else { "$ms" }
        Get-CoreProcs | ForEach-Object { Stop-Process -Force -Id $_.ProcessId -ErrorAction SilentlyContinue }
        Start-Sleep -Milliseconds 500
    }
    $label = if ($how -eq "close") { "正常关闭窗口" } else { "taskkill /F 壳" }
    Emit ("- {0}：freeread-core 清理耗时（ms）{1}" -f $label, ($cleanup -join " / "))
}
$sorted = $startMs | Sort-Object
Emit ("- 壳启动到 /health 可用（ms，{0} 次）：{1}；中位数 {2}" -f $startMs.Count, ($startMs -join " / "), $sorted[[int][Math]::Floor($sorted.Count / 2)])
Emit ("- 数据库 {0}：{1}" -f $dataDb, $(if (Test-Path $dataDb) { "已创建（迁移已执行）" } else { "不存在" }))

Set-Content -Encoding utf8 $Out $lines
Write-Host "结果写入 $Out"
