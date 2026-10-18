# M0：Tauri 2 + Python sidecar 在 Windows 上的验证

- 状态：已完成（数据待汇总进 M0 报告）
- 日期：2026-10-17
- 关联：[ADR-0001](adr/0001-tauri-python-sidecar.md)、[路线图 M0](04-roadmap.md)

## 结论速览

| 项目 | 结果 |
|---|---|
| `npm run tauri build` 生成 NSIS 安装包 | ✅ 17.56 MiB（18,410,502 字节），安装后 21.7 MB |
| 安装、运行，界面显示 `/health` = ok | ✅（静默安装 `/S` 到默认目录 `%LOCALAPPDATA%\FreeRead`） |
| sidecar 热启动到 `/health` 可用 | onefile 中位数 **3.06 s**，onedir 中位数 **1.04 s** |
| 正常关闭后残留 `freeread-core` | ✅ 5/5 次为 0（90–153 ms 内清理完） |
| `taskkill /F` 强杀壳之后残留 `freeread-core` | ✅ 5/5 次为 0（326–377 ms 内清理完） |
| 杀毒扫描 | Kaspersky 按需扫描安装包（解包到 NSIS → PyInstaller → PYZ）：2016 个对象，0 检出。Defender 处于未运行状态，无法扫描 |
| 杀毒软件行为拦截 | ⚠️ 有：Kaspersky HIPS 把无签名的新 exe 放入"低限制"组，出现过安装失败、onefile 无法解压、壳启动失败，详见下文 |

**建议**：发布包改用 PyInstaller `--onedir`（热启动快约 2 s，且不需要往 `%TEMP%` 解压可执行代码，受杀毒软件影响面更小），并尽早做代码签名。

## 环境

- Windows 11 Pro for Workstations 10.0.26300，x86_64
- rustc 1.98、Node 24.18、Tauri 2.12.4、tauri-plugin-shell 2.5.0、create-tauri-app 4.7.5
- Python 3.12.14（uv 管理）、PyInstaller 6.x
- 杀毒软件：Kaspersky 21.26（主防护）；Windows Defender `AMRunningMode = Not running`

## 实现要点

```
freeread-desktop.exe (Tauri 壳)
 └─ freeread-core.exe          PyInstaller onefile 引导进程（externalBin）
     └─ freeread-core.exe      真正的 Python 进程（uvicorn, 127.0.0.1:<随机端口>）
```

- **端口与 token**：壳绑定 `127.0.0.1:0` 取空闲端口后释放，生成 32 字节随机 token（hex），以 `--port <p> --token <t> --parent-pid <壳 PID>` 传给 sidecar；前端通过 `core_info` 命令拿到二者。
- **CORS**：WebView 的源是 `http://tauri.localhost`，请求带自定义头 `X-FreeRead-Token` 会触发预检，所以 core 加了 `CORSMiddleware`，只放行 Tauri 源和 `tauri dev` 的 `http://localhost:1420`。预检不带 token，由中间件直接应答；实际请求仍要校验 token。
- **退出清理三道保险**（`apps/desktop/src-tauri/src/lib.rs`）：
  1. `RunEvent::Exit` 时 `CommandChild::kill()` 引导进程，再 `TerminateJobObject` 结束整棵树。只 kill 引导进程是不够的：onefile 模式下真正的 Python 进程是它的子进程，会成为孤儿。
  2. 子进程启动后立刻放进设置了 `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` 的 Job Object；后代进程自动继承。壳被强杀时由内核关闭最后一个 job 句柄，从而结束整棵树。
     理论上存在竞态：在 `AssignProcessToJobObject` 之前引导进程就派生了子进程。实际上引导进程要先解压约 16 MB，时间窗口远大于这个竞态，测试中没有出现，而且第 3 道保险会兜住这种情况。
  3. sidecar 的 `--parent-pid` 看门狗（`core/freeread/main.py`）：Windows 上用 `OpenProcess(SYNCHRONIZE)` + `WaitForSingleObject` 等待父进程退出（持有句柄，不受 PID 复用影响），POSIX 上每秒轮询一次。父进程消失后先让 uvicorn 优雅退出，5 秒内没退完就 `os._exit`。
- sidecar 启动失败（例如被杀毒软件拦截）不会让壳崩溃：`core_info` 返回错误，界面上会显示原因。

## 测量方法

测量脚本没有放进仓库，方法记在这里，M1 需要时再脚本化。

- **sidecar 启动时间**：PowerShell `Stopwatch` 从 `Start-Process` 开始计时，每 20 ms 用 `HttpClient` 请求一次 `GET /health`（带 token），到返回 200 时停止；然后 `taskkill /T /F` 结束进程，间隔 0.5 s 再进行下一次。
  - **冷启动**：每次都把 exe（onedir 则是整个目录）复制到一个新目录再启动，模拟"安装后第一次启动"。新文件会触发杀毒软件首次扫描，没有清空系统文件缓存（需要 RAMMap / 重启）。
  - **热启动**：同一路径先启动 1 次预热（不计），再连续启动 5 次。
- **壳到界面就绪**：壳记录 sidecar 的启动时刻（`spawnedAtMs`），前端在 `/health` 首次返回 200 时显示两者之差（`#ready-after`）。这个时间通过 WebView2 远程调试端口（`WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=…`）读取。
- **退出清理**：启动已安装的 `freeread-desktop.exe`，等界面显示 ok 后，用 `CloseMainWindow()`（等同于点击关闭按钮）或 `taskkill /F /PID <壳>` 结束壳，然后每 50 ms 检查一次 `Get-Process freeread-core`，最多等 15 s。

## 数据

### 体积

| 产物 | 大小 |
|---|---|
| sidecar onefile `freeread-core-x86_64-pc-windows-msvc.exe` | 15.9 MB |
| sidecar onedir `dist-onedir/freeread-core/` | 34.5 MB（未压缩） |
| 壳 `freeread-desktop.exe`（release, LTO, strip） | 5.7 MB |
| **NSIS 安装包** `FreeRead_0.0.1_x64-setup.exe` | **17.56 MiB** |
| 安装后目录 | 21.7 MB |
| 静默安装耗时（`/S`） | 约 7.2 s |

sidecar 目前只包含 `/health` 实际 import 到的模块（fastapi、pydantic、uvicorn 等），不含 SQLAlchemy、解析引擎和模型。之后 core 引入更多依赖时体积会增长，需要在 M1 复测。

### sidecar 启动到 `/health` 可用（ms，各 5 次）

| 模式 | 1 | 2 | 3 | 4 | 5 | 中位数 |
|---|---|---|---|---|---|---|
| onefile 冷 | 13444 | 12678 | 12850 | 7392 | 13318 | **12850** |
| onefile 热 | 3058 | 3066 | 3054 | 3061 | 3073 | **3061** |
| onedir 冷 | 9511 | 11450 | 9951 | 9177 | 7076 | **9511** |
| onedir 热 | 1048 | 1031 | 1041 | 1037 | 1067 | **1041** |

- 热启动时 onefile 比 onedir 慢约 2 s，这是每次都要把归档解压到 `%TEMP%\_MEIxxxx` 的固定开销。
- 冷启动 7–13 s，主要花在 Kaspersky 对新文件的首次扫描上（onedir 目录里有上百个 `.pyd`/`.dll`）。同一个文件第二次启动后就进入热启动区间。在没有第三方杀毒软件的机器上应明显更快，M1 换一台干净的机器复测。

### 壳启动到界面显示 ok（onefile，ms）

| 场景 | 数值 |
|---|---|
| 安装后首次启动 | 3798 |
| 之后的启动（10 次） | 2267–2964，中位数约 2610 |

前端每 50 ms 探测一次，这部分误差在 50 ms 以内。

### 退出清理

| 方式 | 次数 | 结束后 `Get-Process freeread-core` | 清理耗时 |
|---|---|---|---|
| 正常关闭窗口 | 5 | 每次都为空 | 90–153 ms |
| `taskkill /F` 壳进程 | 5 | 每次都为空 | 326–377 ms |
| 只依靠看门狗（不经过壳，直接杀掉 `--parent-pid` 指向的进程） | 1 | 为空 | 553 ms |

强杀时两道保险同时生效。清理用时（约 0.33 s）比单独靠看门狗（约 0.55 s，包含 uvicorn 优雅退出）短，说明先起作用的是 Job Object。

## 杀毒软件（Kaspersky 21.26）的影响

本机的 Kaspersky 主动防御（HIPS）把所有新编译出来、没有签名、信誉未知的 exe 都归入"低限制"信任组（报告原文："应用程序被放置在受限制组……无法定义信任组"）。实测影响如下：

1. **构建期误报**：`cargo build --release` 编出的 `cookie` crate 构建脚本被判为 `HEUR:Trojan.Win64.Convagent.gen` 并被删除，导致构建失败（os error 32 / 5）。解决办法是在 `src-tauri/Cargo.toml` 里设置 `[profile.release.build-override] opt-level = 1`，让构建脚本的二进制不同于触发误报的版本。不能改用 `debug = true`：那样 cc-rs 会加 `-Z7`，VS 2026 的 `cl.exe` 随后报 D8050。
2. **安装失败**：第一次运行的安装包被归入低限制组，往 `%LOCALAPPDATA%\FreeRead` 写文件时被拒（NSIS 报 `Can't write …\freeread-desktop.exe`），但退出码仍是 0。换成仓库目录作安装目录可以装上。
3. **运行失败**：在已被归入低限制组的路径上：
   - 壳启动时报 `Failed to setup app: 拒绝访问 (os error 5)` 并 panic（WebView2 数据目录在 AppData 下）；
   - onefile sidecar 报 `[PYI-…:ERROR] Could not create temporary directory!`；
   - onedir sidecar 不需要写 `%TEMP%`，仍能正常运行。
4. **复制一份就能运行**：把同样的文件复制到新路径后再运行（包括重新运行一份复制出来的安装包），都没有再被限制，安装和运行全部正常，上面的数据都是这样测出来的。Kaspersky 似乎是在某个文件首次运行时决定它属于哪个信任组；首次运行时为什么会被判为低限制，原因不明，无法稳定复现。
5. 按需扫描（`avp.com SCAN … /i0 /fa`）安装包和 onefile sidecar：0 检出。

对发布的影响：没有签名的安装包在装了 Kaspersky 一类主动防御软件的用户机器上，有一定概率安装失败或启动失败，而且安装程序还会返回成功。必须做 **Authenticode 代码签名**（建议 EV 或 Azure Trusted Signing，以便尽快积累信誉）。另外，onedir 不需要在运行时往 `%TEMP%` 写可执行代码，比 onefile 更不容易被拦截。

## 遗留 / 跟进

- [x] 发布形态改为 onedir：整个 onedir 目录作为 `bundle.resources` 安装到 `<安装目录>/freeread-core/`，壳用 `shell().command()` 启动（`externalBin` 只能带单个 exe）。复测见 [m1/README.md](m1/README.md)。
- [ ] 代码签名（壳、sidecar、安装包）。签名后在装有 Kaspersky 的机器上复测安装和首次启动。
- [x] 在没有第三方杀毒软件的干净 Windows 上复测冷启动（GitHub windows-latest，见 [m1/README.md](m1/README.md)）。
- [ ] （M2）sidecar 启动失败或中途退出时，壳应把 `Terminated` 事件推给前端，而不是让前端等满 30 s 超时。
- [x] M1 core 依赖增加后复测 sidecar 体积和启动时间：热启动中位数本机 1537 ms、CI 1524 ms，没有超过 2 s，暂不做懒加载。1.03 s / 1.52 s 两档跳变的原因留到 M2 查（见 [m1/README.md](m1/README.md)）。
