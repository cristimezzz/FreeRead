#!/usr/bin/env bash
# CI：启动 FreeRead.app 里的壳，确认 sidecar 起来了；再强杀壳，确认 sidecar 由 --parent-pid 看门狗自行退出
# （macOS 没有 Windows 的 Job Object）。对应 Linux 的 scripts/ci/linux_launch_smoke.sh。
# 用法：scripts/ci/macos_launch_smoke.sh <FreeRead.app 路径>
set -euo pipefail
app="$(cd "$1" && pwd)"
shell_bin="$app/Contents/MacOS/freeread-desktop"
core="$app/Contents/Resources/freeread-core/freeread-core"
log="${TMPDIR:-/tmp}/freeread-shell-$$.log"

diagnose() {
  echo "---- 壳的输出 ----"
  cat "$log" || true
  echo "---- 进程 ----"
  # shellcheck disable=SC2009
  ps -axo pid,ppid,stat,etime,args | grep -i '[f]reeread' || true
}

"$shell_bin" > "$log" 2>&1 &
launched=$!
sidecar=""
for _ in $(seq 1 30); do
  sidecar=$(pgrep -o -f "^$core" || true)
  [ -n "$sidecar" ] && break
  sleep 1
done
if [ -z "$sidecar" ]; then
  diagnose
  kill -KILL "$launched" 2> /dev/null || true
  echo "sidecar 30 s 内没有启动"
  exit 1
fi
shell_pid=$(ps -o ppid= -p "$sidecar" | tr -d ' ')
echo "sidecar ${sidecar}，壳 ${shell_pid}：$(ps -o args= -p "$shell_pid")"

kill -KILL "$shell_pid"
for _ in $(seq 1 10); do
  pgrep -f "^$core" > /dev/null || break
  sleep 1
done
if pgrep -f "^$core" > /dev/null; then
  diagnose
  pkill -KILL -f "^$core" || true
  echo "壳退出 10 s 后 sidecar 仍在运行"
  exit 1
fi
echo "壳启动 sidecar、sidecar 随壳退出：通过"
