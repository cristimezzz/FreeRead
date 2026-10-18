<#
.SYNOPSIS
  sidecar 冒烟测试 + 启动时间测量（方法见 docs/m0-tauri-sidecar.md「测量方法」）。

.DESCRIPTION
  每次启动用一个新的空数据目录（所以每次都会跑一遍 Alembic 迁移），从 Start-Process 计时，
  每 20 ms 请求一次 GET /health，到返回 200 为止；然后检查数据库已迁移到 head、
  /llm/providers 可用（提示词已加载，否则 sidecar 启动即失败），最后 taskkill /T /F。

  -Mode warm：同一路径先预热 1 次（不计），再测 -Runs 次。
  -Mode cold：每次把整个 onedir 目录复制到新的临时目录再启动，模拟安装后首次启动
             （新文件会触发杀毒软件首次扫描；没有清空系统文件缓存）。

.EXAMPLE
  pwsh scripts/measure_sidecar.ps1 -Mode warm
  pwsh scripts/measure_sidecar.ps1 -Mode cold -Dir "$env:LOCALAPPDATA\FreeRead\freeread-core"
#>
param(
    [ValidateSet("warm", "cold")][string]$Mode = "warm",
    [int]$Runs = 5,
    [string]$Dir = (Join-Path $PSScriptRoot "../apps/desktop/src-tauri/binaries/freeread-core"),
    [int]$TimeoutSec = 60,
    # 本机 Kaspersky 会拒绝新编出的无签名 exe 写 %TEMP%（见 docs/m0-tauri-sidecar.md），可改到别处
    [string]$WorkRoot = [IO.Path]::GetTempPath()
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Net.Http
$Dir = (Resolve-Path $Dir).Path
$Work = [IO.Path]::GetFullPath((Join-Path $WorkRoot "freeread-measure-$PID"))
New-Item -ItemType Directory -Force $Work | Out-Null

function Get-FreePort {
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    $listener.Start()
    try { $listener.LocalEndpoint.Port } finally { $listener.Stop() }
}

function Measure-Start([string]$ExeDir, [int]$N) {
    $port = Get-FreePort
    $token = [guid]::NewGuid().ToString("N")
    $data = Join-Path $Work "data-$N"
    $client = [Net.Http.HttpClient]::new()
    $client.Timeout = [TimeSpan]::FromSeconds(2)
    $client.DefaultRequestHeaders.Add("X-FreeRead-Token", $token)
    $base = "http://127.0.0.1:$port"
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $proc = Start-Process -PassThru -WindowStyle Hidden `
        -RedirectStandardError (Join-Path $Work "core-$N.err") `
        -RedirectStandardOutput (Join-Path $Work "core-$N.out") `
        -FilePath (Join-Path $ExeDir "freeread-core.exe") `
        -ArgumentList "--port", $port, "--token", $token, "--data-dir", "`"$data`""
    try {
        while ($true) {
            if ($proc.HasExited) {
                Get-Content (Join-Path $Work "core-$N.err") -Tail 15 | Write-Host
                throw "sidecar 提前退出（$($proc.ExitCode)）"
            }
            if ($sw.Elapsed.TotalSeconds -gt $TimeoutSec) { throw "等待 /health 超时" }
            try {
                $resp = $client.GetAsync("$base/health").GetAwaiter().GetResult()
                if ($resp.IsSuccessStatusCode) { break }
            } catch { }
            Start-Sleep -Milliseconds 20
        }
        $ms = $sw.ElapsedMilliseconds
        $providers = $client.GetAsync("$base/llm/providers").GetAwaiter().GetResult()
        if (-not $providers.IsSuccessStatusCode) { throw "/llm/providers 返回 $($providers.StatusCode)" }
        if (-not (Test-Path (Join-Path $data "freeread.db"))) { throw "数据库未创建" }
        if (-not (Select-String -Quiet -Path (Join-Path $Work "core-$N.err") -Pattern "database upgraded")) {
            throw "日志里没有迁移记录（database upgraded）"
        }
        return $ms
    } finally {
        $client.Dispose()
        taskkill /T /F /PID $proc.Id 2>&1 | Out-Null
        Start-Sleep -Milliseconds 500
    }
}

$results = @()
try {
    if ($Mode -eq "warm") {
        Measure-Start $Dir 0 | Out-Null
        foreach ($i in 1..$Runs) { $results += Measure-Start $Dir $i }
    } else {
        foreach ($i in 1..$Runs) {
            $copy = Join-Path $Work "copy-$i"
            Copy-Item -Recurse $Dir $copy
            $results += Measure-Start $copy $i
        }
    }
} finally {
    Remove-Item -Recurse -Force $Work -ErrorAction SilentlyContinue
}
$sorted = $results | Sort-Object
$median = $sorted[[int][Math]::Floor($sorted.Count / 2)]
Write-Host ("{0}: {1} ms；中位数 {2} ms" -f $Mode, ($results -join " / "), $median)
