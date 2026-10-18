<#
.SYNOPSIS
  sidecar 冒烟测试 + 启动时间测量（方法见 docs/m0-tauri-sidecar.md「测量方法」）。

.DESCRIPTION
  每次启动用一个新的空数据目录（所以每次都会跑一遍 Alembic 迁移），从 Start-Process 计时，
  每 20 ms 请求一次 GET /health，到返回 200 为止；然后检查数据库已迁移到 head、
  /llm/providers 可用（提示词已加载，否则 sidecar 启动即失败），导入一个小 PDF 并等快速解析、再检索一次
  （PyMuPDF）完成，最后 taskkill /T /F。解析检查不计入启动时间。

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

# 一页、一行文字的最小 PDF，用来检查打包后的快速解析链路（PyMuPDF 及其包元数据）。
function New-TinyPdf([string]$Path) {
    $stream = "BT /F1 18 Tf 72 720 Td (FreeRead packaging smoke test.) Tj ET"
    $objects = @(
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        "<< /Length $($stream.Length) >>`nstream`n$stream`nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    )
    $sb = [Text.StringBuilder]::new("%PDF-1.4`n")
    $offsets = @()
    for ($i = 0; $i -lt $objects.Count; $i++) {
        $offsets += $sb.Length
        [void]$sb.Append("$($i + 1) 0 obj`n$($objects[$i])`nendobj`n")
    }
    $xref = $sb.Length
    [void]$sb.Append("xref`n0 $($objects.Count + 1)`n0000000000 65535 f `n")
    foreach ($o in $offsets) { [void]$sb.Append(("{0:D10} 00000 n `n" -f $o)) }
    [void]$sb.Append("trailer`n<< /Size $($objects.Count + 1) /Root 1 0 R >>`nstartxref`n$xref`n%%EOF`n")
    [IO.File]::WriteAllText($Path, $sb.ToString(), [Text.Encoding]::ASCII)
}

function Test-Parse($Client, [string]$Base) {
    $pdf = Join-Path $Work "smoke.pdf"
    if (-not (Test-Path $pdf)) { New-TinyPdf $pdf }
    $body = [Net.Http.StringContent]::new((@{ path = $pdf } | ConvertTo-Json), [Text.Encoding]::UTF8, "application/json")
    $resp = $Client.PostAsync("$Base/library/import-file", $body).GetAwaiter().GetResult()
    if (-not $resp.IsSuccessStatusCode) { throw "import-file 返回 $($resp.StatusCode)" }
    $docId = ($resp.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json).item.documents[0].doc_id
    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $deadline) {
        $jobs = $Client.GetStringAsync("$Base/jobs?kind=parse").GetAwaiter().GetResult() | ConvertFrom-Json
        $failed = @($jobs | Where-Object status -in "failed", "cancelled")
        if ($failed) { throw "解析失败：$($failed[0].message)" }
        if ($jobs -and @($jobs | Where-Object status -ne "done").Count -eq 0) {
            # 全文索引（FTS5）随解析写入；连接上能加载 sqlite-vec（vec0.dll），否则 sidecar 启动即失败
            $hits = $Client.GetStringAsync("$Base/documents/$docId/search?q=packaging").GetAwaiter().GetResult() | ConvertFrom-Json
            if (-not $hits.hits) { throw "解析后检索不到文本" }
            return
        }
        Start-Sleep -Milliseconds 200
    }
    throw "30 s 内解析未完成"
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
        Test-Parse $client $base
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
