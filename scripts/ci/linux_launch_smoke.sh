#!/usr/bin/env bash
# CI：在 Xvfb 里启动装好的 FreeRead，确认 sidecar 起来了；再强杀壳，确认 sidecar 由 --parent-pid 看门狗自行退出
# （Linux 没有 Windows 的 Job Object）。用法：dbus-run-session -- scripts/ci/linux_launch_smoke.sh <壳路径> <sidecar 目录>
#
# 壳启动 sidecar 前会从 Secret Service 读 API Key。钥匙串锁着时 Secret Service 会弹解锁框并一直等，
# 没有桌面就永远等不到，所以先在这个 D-Bus 会话里解锁一个空密码的 gnome-keyring。
set -euo pipefail
shell_bin="$1"
core="$2/freeread-core"

printf '\n' | gnome-keyring-daemon --unlock --components=secrets > /dev/null

diagnose() {
  echo "---- 壳的输出 ----"
  cat shell.log || true
  echo "---- 进程 ----"
  ps -eo pid,ppid,stat,etime,args | grep -iE '[f]reeread|[k]eyring' || true
  local pid
  pid=$(pgrep -f "^$shell_bin" | head -n1 || true)
  if [ -n "$pid" ]; then
    echo "---- 壳的线程栈 ----"
    sudo gdb -batch -p "$pid" -ex 'thread apply all bt' 2>/dev/null | grep -E '^(Thread|#)' | head -n 120 || true
  fi
}

xvfb-run -a "$shell_bin" > shell.log 2>&1 &
for _ in $(seq 1 30); do
  pgrep -f "^$core" > /dev/null && break
  sleep 1
done
pgrep -f "^$shell_bin" > /dev/null || { diagnose; echo "壳 30 s 内退出了"; exit 1; }
pgrep -f "^$core" > /dev/null || { diagnose; echo "sidecar 30 s 内没有启动"; exit 1; }

pkill -KILL -f "^$shell_bin"
for _ in $(seq 1 10); do
  pgrep -f "^$core" > /dev/null || break
  sleep 1
done
if pgrep -f "^$core" > /dev/null; then diagnose; echo "壳退出 10 s 后 sidecar 仍在运行"; exit 1; fi
echo "壳启动 sidecar、sidecar 随壳退出：通过"
