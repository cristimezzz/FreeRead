# M1 固定机器验收记录

用户于 2026-10-03 指定本机作为固定验收机器。正式性能验收尚未通过：Electron 在应用代码执行前退出，无法取得本机原生阅读性能数据。

| 项目 | 环境 |
|---|---|
| 系统 | Windows 11 专业工作站版，10.0.26300 / build 26300，x64 |
| CPU | Intel Core i5-12500H，12 核 / 16 线程 |
| 内存 | 16829116416 bytes |
| GPU | Intel Iris Xe / NVIDIA RTX 3050 Ti Laptop；另有 GameViewer Virtual Display Adapter |
| 运行时 | Electron 39.8.10，Chromium 142.0.7444.265，Node 22.22.1 |
| 工程工具 | Node 24.18.1，pnpm 11.21.0 |

实际运行 `pnpm exec playwright test apps/desktop/e2e/shell.e2e.ts` 与 `pnpm test:cold-start`，均在窗口出现前退出，code `2147483651`（`0x80000003`）。用户在普通 PowerShell 运行同一 E2E 也报告 `Process failed to launch`。项目内同版本运行时副本的 `--version` 对照同样失败；`ELECTRON_RUN_AS_NODE=1` 模式可运行。

使用微软签名的 ProcDump 捕获纯 Electron `--version` 启动转储，再用系统 dbgeng 与 Electron 官方同版本 Breakpad 符号定位：

```text
Sandbox::Initialize                sandbox/policy/sandbox.cc:67
ContentMainRunnerImpl::Initialize  content/app/content_main_runner_impl.cc:1006
RunContentProcess                 content/app/content_main.cc:319
ContentMain                       content/app/content_main.cc:357
wWinMain                          electron_main_win.cc:235
```

对应 [Chromium 源码](https://chromium.googlesource.com/chromium/src/+/142.0.7444.265/sandbox/policy/sandbox.cc) 的失败条件为 `CreateAlternateDesktop(kAlternateWinstation)` 返回非成功。转储 EAX 为 12（`SBOX_ERROR_CANNOT_CREATE_WINSTATION`），线程保存的 Windows 错误码为 5（`ERROR_ACCESS_DENIED`）。这定位了失败条件，尚未确定触发它的系统设置。未关闭沙箱或修改系统窗口站权限。

用户授权的运行目录 `S-1-15-2-2` 读/执行权限试验未修复启动；已精确撤回新增规则。诊断转储、工具与原始会话权限信息仅保存在忽略目录 `artifacts/diagnostics/`，不提交到 GitHub。

待启动问题解决后，在此机器执行：

```powershell
pnpm verify
pnpm build:dist
$env:FR_PACKAGED = '1'
pnpm exec playwright test
Remove-Item Env:FR_PACKAGED
pnpm test:cold-start --packaged
```

正式证据应包括 `performance.json`（1000 页首屏、10 秒滚动帧率及机器参数）、20/20 强杀恢复、5/5 正常恢复、renderer 崩溃恢复和冷启动日志。阈值保持首屏 ≤ 3000 ms、滚动 ≥ 55 fps、冷启动 ≤ 2500 ms。GitHub hosted runner 的数值仅证明该次平台冒烟，不代替本机固定机器验收；尚未配置规范要求的自托管性能 runner。
