#!/usr/bin/env bash
# CI：在 Xvfb 里启动装好的 FreeRead，确认 sidecar 起来了；再强杀壳，确认 sidecar 由 --parent-pid 看门狗自行退出
# （Linux 没有 Windows 的 Job Object）。用法：dbus-run-session -- scripts/ci/linux_launch_smoke.sh <启动命令> <sidecar 目录>
#
# 启动命令是 deb 装的壳，或者 AppImage 文件。sidecar 目录拼进 pgrep 的正则，AppImage 挂载点不固定，
# 可以传正则（如 /tmp/\.mount_[^/]*/usr/lib/[^/]*/freeread-core）。壳经 AppImage 的 AppRun 启动时命令行不是
# 启动命令本身，所以壳的进程按 sidecar 的父进程找。
#
# 壳启动 sidecar 前会从 Secret Service 读 API Key。钥匙串锁着时 Secret Service 会弹解锁框并一直等，
# 没有桌面就永远等不到，所以先在这个 D-Bus 会话里解锁一个空密码的 gnome-keyring。
set -euo pipefail
launch="$1"
core="$2/freeread-core"

printf '\n' | gnome-keyring-daemon --unlock --components=secrets > /dev/null

diagnose() {
  echo "---- 壳的输出 ----"
  cat shell.log || true
  echo "---- 进程 ----"
  ps -eo pid,ppid,stat,etime,args | grep -iE '[f]reeread|[k]eyring|[A]ppRun' || true
  local pid
  pid=$(pgrep -f 'freeread-desktop' | head -n1 || true)
  if [ -n "$pid" ]; then
    echo "---- 壳的线程栈 ----"
    sudo gdb -batch -p "$pid" -ex 'thread apply all bt' 2>/dev/null | grep -E '^(Thread|#)' | head -n 120 || true
  fi
}

xvfb-run -a "$launch" > shell.log 2>&1 &
for _ in $(seq 1 30); do
  pgrep -f "^$core" > /dev/null && break
  sleep 1
done
sidecar=$(pgrep -o -f "^$core" || true)
[ -n "$sidecar" ] || { diagnose; echo "sidecar 30 s 内没有启动"; exit 1; }
shell_pid=$(ps -o ppid= -p "$sidecar" | tr -d ' ')
echo "sidecar $sidecar，壳 $shell_pid：$(ps -o args= -p "$shell_pid")"

kill -KILL "$shell_pid"
for _ in $(seq 1 10); do
  pgrep -f "^$core" > /dev/null || break
  sleep 1
done
if pgrep -f "^$core" > /dev/null; then diagnose; echo "壳退出 10 s 后 sidecar 仍在运行"; exit 1; fi
echo "壳启动 sidecar、sidecar 随壳退出：通过"
