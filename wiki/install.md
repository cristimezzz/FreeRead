# 安装

## 系统要求

- Windows 10 / 11，x64
- WebView2 运行时（Windows 11 和较新的 Windows 10 自带；安装包在缺少时会自动安装）
- 可选：Zotero 7（导入文献库）；NVIDIA 显卡（在本机运行 MinerU / Docling 时加速）

## 下载

在 [Releases](https://github.com/cristimezzz/FreeRead/releases) 页面选择：

| 文件 | 适合 |
|---|---|
| `FreeRead_<版本>_x64-setup.exe` | 大多数用户。安装到当前用户目录（`%LOCALAPPDATA%\FreeRead`），不需要管理员权限，有开始菜单快捷方式和卸载入口 |
| `FreeRead_<版本>_x64-portable.zip` | 不想安装、或没有权限运行安装程序时。解压到任意目录，运行 `freeread-desktop.exe` |

便携版只是"免安装"：文献库、设置、缓存仍保存在 `%APPDATA%\FreeRead`，API Key 仍在系统凭据管理器里，与安装版共用，不会随文件夹一起带走。解压后请保持 `freeread-desktop.exe` 与 `freeread-core` 文件夹在同一目录。

## 首次运行提示"Windows 已保护你的电脑"

FreeRead 目前没有代码签名，SmartScreen 会拦截首次运行。点 **更多信息 → 仍要运行** 即可。部分杀毒软件也可能对未签名程序报警，可以把安装目录加入信任。

## 更新

从 0.2.0 起，**设置 › 关于** 里可以检查更新：点 **检查更新** 会查询 GitHub 上的最新 Release（只在点按钮时联网），有新版本时显示更新说明，下载后按 sha256 校验。

- **安装版**：下载完点安装，FreeRead 会关闭，安装包以更新模式运行（只显示进度、保留数据），装好后自动重新打开。
- **便携版**：下载到“下载”文件夹并在资源管理器里选中，由你解压替换旧的 `freeread-desktop.exe` 和 `freeread-core` 文件夹。

0.1.0 没有这个功能，从 0.1.0 升级需要手动下载新版安装包覆盖安装（或替换便携版目录）。文献库、设置和 API Key 都会保留。

## 卸载

在 Windows“设置 › 应用”里卸载 FreeRead。卸载程序里可以勾选 **删除应用数据**：勾选后会一起删除 `%APPDATA%\FreeRead`（文献库、解析结果、译文等）和凭据管理器里保存的 API Key；不勾选则全部保留，重装后可继续使用。

下一步：[快速上手](/quick-start)
