# M1 固定机器验收记录

用户于 2026-10-03 指定本机作为固定验收机器。启动阻塞已定位并解除：保持仓库低完整性标签，在普通系统临时目录运行字节一致的打包版。原生功能和千页性能通过，冷启动首次测量超预算仍保留为未解决的稳定性风险。

| 项目 | 环境 |
|---|---|
| 系统 | Windows 11 专业工作站版，26H2 / 10.0.26300.9457，x64 |
| CPU | Intel Core i5-12500H，12 核 / 16 线程 |
| 内存 | 16829116416 bytes |
| GPU | Intel Iris Xe / NVIDIA RTX 3050 Ti Laptop；另有 GameViewer Virtual Display Adapter |
| 运行时 | Electron 39.8.10，Chromium 142.0.7444.265，Node 22.22.1 |
| 工程工具 | Node 24.18.1，pnpm 11.21.0 |
| 打包版 | M1 Windows x64；构建清单为 `7c0d62d` + dirty，包含本次依赖内联/验证器延迟编译修改 |
| 可执行文件 SHA256 | `94BE5DB1D8DFBA4DF4B62410BAB5FDA8027DAF2106682394CD2AE951DA81FD40` |
| app.asar SHA256 | `6E2638B9957695899BB9A9DD0BB5E8F4EA963E63D8E1B692DE16E4FBEDCF2906` |

## 本机原生结果

- 打包版完整 E2E：4/4，通过导入/去重、标签/FTS、标注和笔记重启、renderer 崩溃重载、20/20 进程树强杀恢复，以及沙箱/零 Node 特权断言。
- E4 加强验证：将原来仅往返文献库的五次恢复，改为真正关闭并重启整个应用；单独实跑 1/1 通过，之后也包含在优化版完整 4/4 E2E 中通过。
- 优化版 1000 页首屏 402.93 ms、连续滚动 10 秒 120.14 fps、canvas ≤ 5，均通过。机器参数和运行时版本见 [原始测量 JSON](assets/m1-local-performance.json)；该样本是合成文本 PDF。
- 独立冷启动：每次启动新进程、使用新用户目录，不连接调试器。全部结果见 [冷启动原始记录](assets/m1-local-cold-start.txt)。旧版两个全新目录的首次启动分别为 3269 / 3308 ms；内联 AJV/Zod 后为 3014 ms，再延迟编译未使用的验证器后为 2851 ms。优化版在已有安装路径中的五次复测为 988–1146 ms，均通过。首次启动超时仍保留，不据后续通过删除失败或定义采样豁免。

| 旧版测量 | 完整启动 | native bootstrap | main 至首帧 | 2500 ms 门禁 |
|---|---:|---:|---:|---|
| 暂存后首次 | 3269 ms | 2085 ms | 1184 ms | 失败 |
| 复测 1 | 1498 ms | 597 ms | 901 ms | 通过 |
| 复测 2 | 1371 ms | 688 ms | 683 ms | 通过 |
| 复测 3 | 1329 ms | 690 ms | 639 ms | 通过 |
| 复测 4 | 1290 ms | 670 ms | 620 ms | 通过 |
| 复测 5 | 1291 ms | 657 ms | 634 ms | 通过 |

| 优化与复测 | 完整启动 | app.main 日志之前 | 日志至首帧 | 门禁 |
|---|---:|---:|---:|---|
| 旧版第二个全新目录 | 3308 ms | 2246 ms | 1062 ms | 失败 |
| AJV/Zod 内联，全新目录首次 | 3014 ms | 2036 ms | 978 ms | 失败 |
| 内联 + 延迟编译，全新目录首次 | 2851 ms | 1732 ms | 1119 ms | 失败 |
| 最终版复测 1 | 1146 ms | 237 ms | 909 ms | 通过 |
| 最终版复测 2 | 1055 ms | 301 ms | 754 ms | 通过 |
| 最终版复测 3 | 1062 ms | 323 ms | 739 ms | 通过 |
| 最终版复测 4 | 988 ms | 302 ms | 686 ms | 通过 |
| 最终版复测 5 | 1063 ms | 320 ms | 743 ms | 通过 |

软件渲染诊断对照（额外 `--disable-gpu`）首次 2749 ms，仍失败；正式应用和验收脚本未加入该开关。`native bootstrap` 是脚本的阶段名，实际包括原生初始化与主模块加载/顶层求值，因为 `app.main` 在静态 imports 后输出。首次路径的额外 I/O / 系统扫描原因仍未证实。建议延长首次冷启动的定位与优化时间，保持 2500 ms 预算。规范要求的自托管性能 runner 仍未配置；三平台 hosted CI 仅作为平台冒烟，完整性能验收保持部分完成。

## 启动故障根因与处理

仓库根目录带 `Mandatory Label\Low Mandatory Level:(OI)(CI)(NW)`；`electron.exe`、`FreeRead.exe` 及在仓库内编译的独立 Windows API 探针均继承低标签。父 PowerShell 是中完整性 `S-1-16-8192`，这些子进程是低完整性 `S-1-16-4096`，并非 AppContainer，Job UI restrictions 为 0。独立探针不加载 Electron，也在 `CreateWindowStationW` 返回错误 5。用户从 Windows 开始菜单打开 PowerShell 运行探针同样失败，纯 Electron `--version` 无输出。

微软 [Mandatory Integrity Control / Process Creation](https://learn.microsoft.com/en-us/windows/win32/secauthz/mandatory-integrity-control) 说明，进程完整性级别取用户与可执行文件级别的较低值；即使由普通或管理员账户启动，低标签程序仍以低完整性运行。

将同一探针复制到普通系统临时目录后，新副本以中完整性运行；复制 DACL 和默认 DACL 两种窗口站创建都成功。相同处理用于当前打包版，核对可执行文件 SHA256 相同，原生验收随即可运行。未修改仓库完整性标签、系统窗口站权限、用户目录权限，也未关闭 Electron 沙箱。

先前微软签名 ProcDump + 系统 dbgeng + Electron 官方符号定位到 `Sandbox::Initialize`（[Chromium 源码](https://chromium.googlesource.com/chromium/src/+/142.0.7444.265/sandbox/policy/sandbox.cc) §67）的 `CreateAlternateDesktop(kAlternateWinstation)` 失败：EAX 为 12（`SBOX_ERROR_CANNOT_CREATE_WINSTATION`）。本次实时断点进一步确认 `CreateWindowStationW` 两次请求 `0x80000008` 与 `0xA` 都返回 NULL、Windows 错误 5。用户授权的目录 `S-1-15-2-2` RX 权限试验无效且已撤回；它不能改变进程完整性级别。

诊断转储、原始 ACL、工具与探针均留在忽略目录 `artifacts/diagnostics/`，不提交 GitHub。此前本机完整 `pnpm build:dist` 未取得成功退出记录，NSIS 安装包不能视为完成；完整打包证据见 [三平台 CI](https://github.com/cristimezzz/FreeRead/actions/runs/37119627119)。

## 复现

在普通 PowerShell 中，已有 `artifacts/win-unpacked` Windows x64 包时执行：

```powershell
pnpm verify
pwsh -File C:\Projects\FreeRead\docs\run-m1-native-acceptance.ps1
```

脚本把同一打包版暂存到系统临时目录、验证 exe 哈希，依次运行独立冷启动与完整 E2E；保持原始退出码门禁。暂存路径会输出，保留供检查，截图在该路径的 `test-results/`，测量和测试附件在仓库 `artifacts/m1-local-evidence/`。结束后还原工作目录与 `FR_PACKAGED`；不注册 runner 或修改权限。仓库内直接启动低标签 exe 仍会失败，正常安装目录或此暂存路径可运行。
