# Rust 构建加速

- 日期：2026-10-20
- 范围：桌面壳（`apps/desktop/src-tauri`），本机与 CI

## 现状（改动前）

| 任务 | 耗时 | 原因 |
|---|---|---|
| CI `Desktop shell (Rust, Windows)`：fmt + clippy | 约 2 min，其中编译 18 s | Rust 缓存命中，已经不慢 |
| CI `Desktop build (Windows installer)` | 约 14.5 min，其中 `tauri build` 10.5 min | **Rust 缓存从来没命中**（日志 `No cache found`），且 release 用 fat LTO + `codegen-units = 1` |

安装包工作流只在 PR 上触发，缓存只存在各个 PR 分支里。GitHub Actions 的缓存可以从基础分支（main）读，不能跨 PR 分支读，所以每个新 PR 都从零编译全部依赖。

## 已做

### CI（`.github/workflows/desktop-build.yml`）

1. **合并到 main 时也跑一次**（同样的路径过滤），把依赖缓存存到 main，之后的 PR 都能读到。`rust-cache` 用固定的 `shared-key: desktop-release`。
2. **内部测试安装包用 thin LTO + `codegen-units = 16`**（工作流里用 `CARGO_PROFILE_RELEASE_*` 环境变量覆盖，不改 Cargo.toml）。fat LTO + 单代码生成单元把整个程序放在一个线程里优化，是 release 构建最慢的一步；thin LTO 并行做，体积略大。正式发布构建仍用 Cargo.toml 的完整设置。main 与 PR 必须用同一组设置，否则依赖的编译指纹不同，缓存无效。
3. 同一分支新提交时取消正在跑的安装包构建（`concurrency`）。

### 本机（`Cargo.toml`、`.cargo/config.toml`）

1. **链接器换成 `rust-lld`**（随 rustup 安装，不需要另装工具）。每次增量构建都要重新链接整个程序，lld 比 MSVC `link.exe` 快得多。CI 也会用它（clippy 编译构建脚本时链接）。有问题时删掉 `.cargo/config.toml` 的那一段即可回到 `link.exe`。
2. **开发构建减少调试信息**：本 crate `debug = "line-tables-only"`（panic 回溯仍有行号），依赖 `debug = false`。Windows 上 PDB 的生成与链接占开发构建的很大一部分。要在调试器里单步依赖代码时临时改回 `debug = true`。

## 没做、可以自己选的

- **把 `target/` 和 `~/.cargo` 加入杀毒软件排除**（Defender / Kaspersky）。Windows 上实时扫描对编译中大量的小文件影响很大；M0 记录过 Kaspersky 还会锁住新编出的构建脚本。Windows 11 的 **Dev Drive**（ReFS + 性能模式）效果类似，可以把仓库放在 Dev Drive 上。
- 日常改壳代码用 `cargo check` / `cargo clippy` 或 `npm run tauri dev`（debug 构建），不要用 `tauri build`（release + LTO）验证。
- `sccache`：只有一个 Rust 项目，本机收益不大；CI 已有 `rust-cache`。

## 验证

- `rust-lld` 在本机（rustc 1.98.1，`x86_64-pc-windows-msvc`）链接测试 crate 正常；完整的壳链接由本 PR 的 CI（clippy 构建脚本 + 安装包构建）验证。
- 本 PR 改了安装包工作流，会触发一次构建：这次没有 main 缓存，只能看到 thin LTO 的效果和安装包体积变化；合并后的 main 构建会存缓存，下一个 PR 才能看到缓存效果。
