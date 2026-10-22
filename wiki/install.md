# 安装

## 系统要求

**Windows**

- Windows 10 / 11，x64
- WebView2 运行时（Windows 11 和较新的 Windows 10 自带；安装包在缺少时会自动安装）

**Linux**（0.2.0 之后的版本起）

- x86_64，glibc 2.35 以上：Ubuntu 22.04、Debian 12、Fedora 36、openSUSE Tumbleweed、Arch 及更新的发行版
- WebKitGTK 4.1（包管理器会自动安装）
- 一个 Secret Service 服务用来保存 API Key：GNOME 自带 GNOME Keyring，KDE 的 KWallet 也支持；没有时 API Key 无法保存

**通用**

- 可选：Zotero 7（导入文献库）；NVIDIA 显卡（在本机运行 MinerU / Docling 时加速）

## 下载

在 [Releases](https://github.com/cristimezzz/FreeRead/releases) 页面选择：

| 文件 | 适合 |
|---|---|
| `FreeRead_<版本>_x64-setup.exe` | Windows 大多数用户。安装到当前用户目录（`%LOCALAPPDATA%\FreeRead`），不需要管理员权限，有开始菜单快捷方式和卸载入口 |
| `FreeRead_<版本>_x64-portable.zip` | Windows 上不想安装、或没有权限运行安装程序时。解压到任意目录，运行 `freeread-desktop.exe` |
| `FreeRead_<版本>_amd64.AppImage` | 任意 Linux 发行版，免安装，单个文件 |
| `FreeRead_<版本>_amd64.deb` | Debian、Ubuntu 及其衍生版 |
| `FreeRead-<版本>-1.x86_64.rpm` | Fedora、openSUSE 等 |

便携版只是"免安装"：文献库、设置、缓存仍保存在 `%APPDATA%\FreeRead`，API Key 仍在系统凭据管理器里，与安装版共用，不会随文件夹一起带走。解压后请保持 `freeread-desktop.exe` 与 `freeread-core` 文件夹在同一目录。

## Linux 安装

AppImage（任意发行版，不需要 root）：

```bash
chmod +x FreeRead_<版本>_amd64.AppImage
./FreeRead_<版本>_amd64.AppImage
```

AppImage 需要 FUSE 2（Ubuntu 22.04 起要先 `sudo apt install libfuse2`，Ubuntu 24.04 起是 `libfuse2t64`）；装不了时可以用 `./FreeRead_<版本>_amd64.AppImage --appimage-extract-and-run` 运行。AppImage 不会加到应用菜单里，可以用 AppImageLauncher 之类的工具集成。

Debian / Ubuntu：

```bash
sudo apt install ./FreeRead_<版本>_amd64.deb
```

Fedora：

```bash
sudo dnf install ./FreeRead-<版本>-1.x86_64.rpm
```

openSUSE 用 `sudo zypper install ./FreeRead-<版本>-1.x86_64.rpm`。

Arch：从 AUR 安装 [`freeread-bin`](https://aur.archlinux.org/packages/freeread-bin)，例如

```bash
yay -S freeread-bin
```

用包管理器装好后在应用菜单里找 FreeRead。程序装在 `/usr/lib/FreeRead`；无论哪种方式，文献库、设置、缓存保存在 `~/.local/share/FreeRead`（设置了 `XDG_DATA_HOME` 时在其下），API Key 保存在 Secret Service（GNOME Keyring / KWallet）里。

## 首次运行提示"Windows 已保护你的电脑"

FreeRead 目前没有代码签名，SmartScreen 会拦截首次运行。点 **更多信息 → 仍要运行** 即可。部分杀毒软件也可能对未签名程序报警，可以把安装目录加入信任。

## 更新

从 0.2.0 起，**设置 › 关于** 里可以检查更新：点 **检查更新** 会查询 GitHub 上的最新 Release（只在点按钮时联网），有新版本时显示更新说明，下载后按 sha256 校验。

- **Windows 安装版**：下载完点安装，FreeRead 会关闭，安装包以更新模式运行（只显示进度、保留数据），装好后自动重新打开。
- **Windows 便携版**：下载到“下载”文件夹并在资源管理器里选中，由你解压替换旧的 `freeread-desktop.exe` 和 `freeread-core` 文件夹。
- **Linux AppImage**：下载新的 AppImage 到“下载”文件夹（已加上可执行权限）并打开该文件夹，退出 FreeRead 后用它替换旧文件即可。
- **Linux deb / rpm**：下载同类安装包到“下载”文件夹并打开该文件夹，退出 FreeRead 后用上面的 `apt install` / `dnf install` 命令安装新包即可覆盖旧版本。
- **AUR**：不在应用里下载，用 AUR 助手更新（例如 `yay -Syu`）。

0.1.0 没有这个功能，从 0.1.0 升级需要手动下载新版安装包覆盖安装（或替换便携版目录）。文献库、设置和 API Key 都会保留。

## 卸载

**Windows**：在“设置 › 应用”里卸载 FreeRead。卸载程序里可以勾选 **删除应用数据**：勾选后会一起删除 `%APPDATA%\FreeRead`（文献库、解析结果、译文等）和凭据管理器里保存的 API Key；不勾选则全部保留，重装后可继续使用。

**Linux**：用包管理器卸载，软件包名是 `free-read`（AUR 上是 `freeread-bin`）：

```bash
sudo apt remove free-read      # Debian / Ubuntu
sudo dnf remove free-read      # Fedora
yay -R freeread-bin            # Arch
```

AppImage 直接删掉文件即可。

卸载不会删除数据。要彻底清除，再删掉 `~/.local/share/FreeRead`，并在“密码和密钥”（Seahorse）或 KWallet 里删除名为 FreeRead 的条目。

下一步：[快速上手](/quick-start)
