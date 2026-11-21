#!/usr/bin/env bash
# sidecar 冒烟测试 + 启动时间测量（方法见 docs/m0-tauri-sidecar.md「测量方法」）。Linux / macOS 用；
# Windows 用 scripts/measure_sidecar.ps1，两边的检查保持一致。
#
# 每次启动用一个新的空数据目录（所以每次都会跑一遍 Alembic 迁移），从启动进程计时，
# 每 20 ms 请求一次 GET /health，到返回 200 为止；然后检查数据库已迁移到 head、
# /llm/providers 可用（提示词已加载），导入一个小 PDF 并等快速解析、再检索一次（PyMuPDF），
# 最后连同子进程强制结束。解析检查不计入启动时间。
#
#   --mode warm：同一路径先预热 1 次（不计），再测 --runs 次。
#   --mode cold：每次把整个 onedir 目录复制到新的临时目录再启动，模拟安装后首次启动。
#
# 用法：scripts/measure_sidecar.sh [--mode warm|cold] [--runs 5] [--dir <onedir>] [--timeout 60] [--work-root <dir>]
# 依赖 curl、jq、perl；要兼容 macOS 自带的 bash 3.2。
set -euo pipefail

mode=warm
runs=5
dir="$(cd "$(dirname "$0")/.." && pwd)/apps/desktop/src-tauri/binaries/freeread-core"
timeout_sec=60
work_root="${TMPDIR:-/tmp}"
while [ $# -gt 0 ]; do
  case "$1" in
    --mode) mode="$2"; shift 2 ;;
    --runs) runs="$2"; shift 2 ;;
    --dir) dir="$2"; shift 2 ;;
    --timeout) timeout_sec="$2"; shift 2 ;;
    --work-root) work_root="$2"; shift 2 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done
case "$mode" in warm | cold) ;; *) echo "--mode 只能是 warm 或 cold" >&2; exit 2 ;; esac

dir=$(cd "$dir" && pwd)
work="${work_root%/}/freeread-measure-$$"
mkdir -p "$work"
trap 'rm -rf "$work"' EXIT

now_ms() { perl -MTime::HiRes=time -e 'printf "%d\n", time * 1000'; }
free_port() { perl -MIO::Socket::INET -e 'print IO::Socket::INET->new(Listen => 1, LocalAddr => "127.0.0.1", LocalPort => 0)->sockport'; }

# 一页、一行文字的最小 PDF，用来检查打包后的快速解析链路（PyMuPDF 及其包元数据）。
new_tiny_pdf() {
  local stream="BT /F1 18 Tf 72 720 Td (FreeRead packaging smoke test.) Tj ET"
  local nl=$'\n'
  local o1="<< /Type /Catalog /Pages 2 0 R >>"
  local o2="<< /Type /Pages /Kids [3 0 R] /Count 1 >>"
  local o3="<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
  local o4="<< /Length ${#stream} >>${nl}stream${nl}${stream}${nl}endstream"
  local o5="<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
  local pdf="%PDF-1.4${nl}" offsets="" i obj
  i=1
  for obj in "$o1" "$o2" "$o3" "$o4" "$o5"; do
    offsets="$offsets $(printf '%010d' "${#pdf}")"
    pdf="${pdf}${i} 0 obj${nl}${obj}${nl}endobj${nl}"
    i=$((i + 1))
  done
  local xref=${#pdf}
  pdf="${pdf}xref${nl}0 6${nl}0000000000 65535 f ${nl}"
  for obj in $offsets; do pdf="${pdf}${obj} 00000 n ${nl}"; done
  pdf="${pdf}trailer${nl}<< /Size 6 /Root 1 0 R >>${nl}startxref${nl}${xref}${nl}%%EOF${nl}"
  printf '%s' "$pdf" > "$1"
}

# 以下函数用全局变量 base / token / log
api() { curl -sS --max-time 5 -H "X-FreeRead-Token: $token" "$@"; }

test_parse() {
  local pdf="$work/smoke.pdf" resp doc_id jobs deadline hits
  [ -f "$pdf" ] || LC_ALL=C new_tiny_pdf "$pdf"
  resp=$(api -w '\n%{http_code}' -H 'Content-Type: application/json' \
    -d "$(jq -n --arg p "$pdf" '{path: $p}')" "$base/library/import-file")
  if [ "$(printf '%s' "$resp" | tail -n1)" != 200 ]; then
    echo "import-file 返回 $(printf '%s' "$resp" | tail -n1)：$(printf '%s' "$resp" | sed '$d')" >&2
    return 1
  fi
  doc_id=$(printf '%s' "$resp" | sed '$d' | jq -r '.item.documents[0].doc_id')
  deadline=$(($(now_ms) + 30000))
  while [ "$(now_ms)" -lt "$deadline" ]; do
    jobs=$(api "$base/jobs?kind=parse")
    if printf '%s' "$jobs" | jq -e 'map(select(.status == "failed" or .status == "cancelled")) | length > 0' > /dev/null; then
      echo "解析失败：$(printf '%s' "$jobs" | jq -r 'map(select(.status == "failed" or .status == "cancelled"))[0].message')" >&2
      return 1
    fi
    if printf '%s' "$jobs" | jq -e 'length > 0 and all(.status == "done")' > /dev/null; then
      # 全文索引（FTS5）随解析写入；连接上能加载 sqlite-vec，否则 sidecar 启动即失败
      hits=$(api "$base/documents/$doc_id/search?q=packaging")
      printf '%s' "$hits" | jq -e '.hits | length > 0' > /dev/null || { echo "解析后检索不到文本" >&2; return 1; }
      return 0
    fi
    sleep 0.2
  done
  echo "30 s 内解析未完成" >&2
  return 1
}

# 测一次，结果写到全局变量 ms
measure_start() {
  local exe_dir="$1" n="$2" port data pid start status
  port=$(free_port)
  token=$(od -An -tx1 -N16 /dev/urandom | tr -d ' \n')
  data="$work/data-$n"
  base="http://127.0.0.1:$port"
  log="$work/core-$n.err"
  start=$(now_ms)
  "$exe_dir/freeread-core" --port "$port" --token "$token" --data-dir "$data" \
    > "$work/core-$n.out" 2> "$log" &
  pid=$!
  status=0
  (
    set -e
    while true; do
      if ! kill -0 "$pid" 2> /dev/null; then
        echo "sidecar 提前退出" >&2
        exit 1
      fi
      [ $(($(now_ms) - start)) -le $((timeout_sec * 1000)) ] || { echo "等待 /health 超时" >&2; exit 1; }
      [ "$(api -o /dev/null -w '%{http_code}' --max-time 2 "$base/health" 2> /dev/null || true)" = 200 ] && break
      sleep 0.02
    done
    echo $(($(now_ms) - start)) > "$work/ms-$n"
    code=$(api -o /dev/null -w '%{http_code}' "$base/llm/providers")
    [ "$code" = 200 ] || { echo "/llm/providers 返回 $code" >&2; exit 1; }
    [ -f "$data/freeread.db" ] || { echo "数据库未创建" >&2; exit 1; }
    grep -q "database upgraded" "$log" || { echo "日志里没有迁移记录（database upgraded）" >&2; exit 1; }
    test_parse
  ) || status=$?
  if [ "$status" -ne 0 ]; then
    # sidecar 的日志在工作目录里，结束时会删掉：失败时先打出来
    echo "---- freeread-core 日志（core-$n.err 末尾）----" >&2
    tail -n 60 "$log" >&2 || true
  fi
  pkill -KILL -P "$pid" 2> /dev/null || true
  kill -KILL "$pid" 2> /dev/null || true
  wait "$pid" 2> /dev/null || true
  sleep 0.5
  [ "$status" -eq 0 ] || exit "$status"
  ms=$(cat "$work/ms-$n")
}

results=""
if [ "$mode" = warm ]; then
  measure_start "$dir" 0
  for i in $(seq 1 "$runs"); do
    measure_start "$dir" "$i"
    results="$results $ms"
  done
else
  for i in $(seq 1 "$runs"); do
    cp -R "$dir" "$work/copy-$i"
    measure_start "$work/copy-$i" "$i"
    results="$results $ms"
  done
fi

# $results 是空格分隔的数字，这里要按词拆开
# shellcheck disable=SC2086
sorted=$(printf '%s\n' $results | sort -n)
count=$(printf '%s\n' "$sorted" | wc -l | tr -d ' ')
median=$(printf '%s\n' "$sorted" | sed -n "$((count / 2 + 1))p")
# shellcheck disable=SC2086
joined=$(printf '%s\n' $results | paste -sd/ - | sed 's#/# / #g')
echo "$mode: $joined ms；中位数 $median ms"
