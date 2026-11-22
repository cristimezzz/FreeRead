//! 检查与下载更新、列出贡献者：数据来自 GitHub 上的 Release 与仓库贡献者，只在设置页「关于」里用到。
//!
//! 不用 tauri-plugin-updater：它要签名密钥和 latest.json，而 Release 只附 NSIS 安装包、便携版 zip、
//! AppImage / deb / rpm 和 macOS 的 dmg（.github/workflows/desktop-build.yml）。下载完按 Release 资源自带的 sha256 校验。
//!
//! - 安装版（exe 旁边有 NSIS 的 uninstall.exe）：下载 `*-setup.exe` 到临时目录，以 `/P /UPDATE /R`
//!   运行（与 tauri-plugin-updater 相同：只显示进度、跳过重装询问、不删数据、装完重新打开），随即退出；
//! - 便携版：下载 `*-portable.zip` 到「下载」文件夹，在资源管理器里选中，由用户自己解压替换；
//! - Linux AppImage：下载新的 AppImage 到「下载」文件夹（加上可执行权限）并打开该文件夹，由用户替换旧文件；
//! - Linux deb / rpm：下载同类包到「下载」文件夹并打开该文件夹，由用户用包管理器安装（要 root）；
//! - AUR（Arch 上装的 freeread-bin，是 deb 解包的）：不下载，由 AUR 助手更新；
//! - macOS（.app 包里运行）：下载 `*_aarch64.dmg` 到临时目录，挂载后把新版复制到旧版旁边、换名，
//!   退出后重新打开（见 [`macos`]）；替换不了（例如没有写入权限）时在 Finder 里显示 dmg，由用户手动安装。

use std::fs::File;
use std::io::Write;
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use tauri::{AppHandle, Emitter, Manager, State};

const REPO: &str = "cristimezzz/FreeRead";
const USER_AGENT: &str = concat!("FreeRead/", env!("CARGO_PKG_VERSION"));

#[derive(Clone, Debug, Deserialize)]
struct GhAsset {
    name: String,
    size: u64,
    browser_download_url: String,
    /// 形如 `sha256:<hex>`；较早上传的资源没有这个字段。
    digest: Option<String>,
}

#[derive(Deserialize)]
struct GhRelease {
    tag_name: String,
    body: Option<String>,
    html_url: String,
    published_at: Option<String>,
    assets: Vec<GhAsset>,
}

#[derive(Deserialize)]
struct GhContributor {
    login: String,
    avatar_url: String,
    html_url: String,
    contributions: u64,
    #[serde(rename = "type")]
    kind: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Contributor {
    login: String,
    avatar_url: String,
    html_url: String,
    contributions: u64,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdateInfo {
    current: String,
    latest: String,
    available: bool,
    notes: String,
    release_url: String,
    published_at: Option<String>,
    /// 适合当前安装方式的下载包；Release 里没有时为 `None`（只能去网页下载）。
    asset: Option<AssetInfo>,
    kind: InstallKind,
}

/// 当前程序的安装方式，决定下载哪个包、下载完怎么处理。
#[derive(Clone, Copy, Debug, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
#[allow(dead_code)] // 每个平台只构造其中几种
pub enum InstallKind {
    /// Windows NSIS 安装版
    Nsis,
    /// Windows 便携版 zip
    Portable,
    Deb,
    Rpm,
    /// Linux AppImage
    AppImage,
    /// Arch 上从 AUR 装的 freeread-bin
    Aur,
    /// macOS 上从 dmg 拖进去的 FreeRead.app
    MacApp,
    /// 认不出来（开发构建、自己解包的等），只给 Release 链接
    Unknown,
}

impl InstallKind {
    /// Release 里对应的包名后缀（Windows / Linux 是 x86_64，macOS 是 arm64）；没有可直接用的包时为 `None`。
    fn asset_suffix(self) -> Option<&'static str> {
        match self {
            Self::Nsis => Some("-setup.exe"),
            Self::Portable => Some("-portable.zip"),
            Self::Deb => Some("_amd64.deb"),
            Self::Rpm => Some(".x86_64.rpm"),
            Self::AppImage => Some("_amd64.AppImage"),
            Self::MacApp => Some("_aarch64.dmg"),
            Self::Aur | Self::Unknown => None,
        }
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AssetInfo {
    name: String,
    size: u64,
}

/// 事件 `update-progress` 的 payload。
#[derive(Clone, Serialize)]
struct Progress {
    received: u64,
    total: u64,
}

/// 最近一次检查到的下载包，和已下载完成的文件。下载只认这里记下的地址，不接受前端传来的 URL。
#[derive(Default)]
pub struct UpdateState {
    asset: Mutex<Option<GhAsset>>,
    downloaded: Mutex<Option<PathBuf>>,
}

fn client() -> Result<reqwest::Client, String> {
    reqwest::Client::builder()
        .user_agent(USER_AGENT)
        .connect_timeout(Duration::from_secs(15))
        .build()
        .map_err(|e| e.to_string())
}

async fn github_json<T: for<'de> Deserialize<'de>>(path: &str) -> Result<T, String> {
    let resp = client()?
        .get(format!("https://api.github.com/repos/{REPO}/{path}"))
        .header("Accept", "application/vnd.github+json")
        .timeout(Duration::from_secs(20))
        .send()
        .await
        .map_err(|e| format!("无法连接 GitHub：{e}"))?;
    match resp.status().as_u16() {
        200 => resp.json().await.map_err(|e| e.to_string()),
        403 | 429 => Err("GitHub 接口请求过于频繁，请稍后再试".into()),
        404 => Err("还没有发布任何版本".into()),
        s => Err(format!("GitHub 返回 HTTP {s}")),
    }
}

/// Windows：有 NSIS 卸载程序的是安装版，否则是便携版 zip 解压出来的。
#[cfg(windows)]
fn install_kind() -> InstallKind {
    let installed = std::env::current_exe()
        .map(|exe| exe.with_file_name("uninstall.exe").is_file())
        .unwrap_or(false);
    if installed {
        InstallKind::Nsis
    } else {
        InstallKind::Portable
    }
}

/// Linux：打包时 tauri-bundler 把包类型写进了可执行文件。AUR 的 freeread-bin 是 deb 解包的，
/// 所以在 Arch 上看到 deb 当作 AUR 安装。
#[cfg(target_os = "linux")]
fn install_kind() -> InstallKind {
    use tauri::utils::{config::BundleType, platform::bundle_type};
    match bundle_type() {
        Some(BundleType::Deb) if std::path::Path::new("/etc/arch-release").exists() => {
            InstallKind::Aur
        }
        Some(BundleType::Deb) => InstallKind::Deb,
        Some(BundleType::Rpm) => InstallKind::Rpm,
        Some(BundleType::AppImage) => InstallKind::AppImage,
        _ => InstallKind::Unknown,
    }
}

/// macOS：tauri 的 `bundle_type()` 在 macOS 上总是 `App`（开发构建也是），所以看可执行文件
/// 是否在某个 `.app` 包里。
#[cfg(target_os = "macos")]
fn install_kind() -> InstallKind {
    if macos::current_bundle().is_some() {
        InstallKind::MacApp
    } else {
        InstallKind::Unknown
    }
}

#[cfg(not(any(windows, target_os = "linux", target_os = "macos")))]
fn install_kind() -> InstallKind {
    InstallKind::Unknown
}

/// `v0.2.0` 是否比 `current` 新；解析不了的标签当作不新。
fn is_newer(tag: &str, current: &str) -> bool {
    match (
        semver::Version::parse(tag.trim_start_matches('v')),
        semver::Version::parse(current),
    ) {
        (Ok(latest), Ok(current)) => latest > current,
        _ => false,
    }
}

fn pick_asset(assets: &[GhAsset], kind: InstallKind) -> Option<&GhAsset> {
    let suffix = kind.asset_suffix()?;
    assets.iter().find(|a| a.name.ends_with(suffix))
}

#[tauri::command]
pub async fn check_update(
    app: AppHandle,
    state: State<'_, UpdateState>,
) -> Result<UpdateInfo, String> {
    let release: GhRelease = github_json("releases/latest").await?;
    let current = app.package_info().version.to_string();
    let kind = install_kind();
    let asset = pick_asset(&release.assets, kind).cloned();
    let info = UpdateInfo {
        available: is_newer(&release.tag_name, &current),
        current,
        latest: release.tag_name.trim_start_matches('v').to_owned(),
        notes: release.body.unwrap_or_default(),
        release_url: release.html_url,
        published_at: release.published_at,
        asset: asset.as_ref().map(|a| AssetInfo {
            name: a.name.clone(),
            size: a.size,
        }),
        kind,
    };
    *state.asset.lock().unwrap() = asset;
    *state.downloaded.lock().unwrap() = None;
    Ok(info)
}

/// 仓库贡献者，按提交数排序（GitHub 的默认顺序），去掉机器人账号。
#[tauri::command]
pub async fn list_contributors() -> Result<Vec<Contributor>, String> {
    let list: Vec<GhContributor> = github_json("contributors?per_page=100").await?;
    Ok(list
        .into_iter()
        .filter(|c| c.kind == "User")
        .map(|c| Contributor {
            login: c.login,
            avatar_url: c.avatar_url,
            html_url: c.html_url,
            contributions: c.contributions,
        })
        .collect())
}

/// 下载最近一次检查到的包，边下边发 `update-progress`，完成后校验大小和 sha256。返回保存的路径。
#[tauri::command]
pub async fn download_update(
    app: AppHandle,
    state: State<'_, UpdateState>,
) -> Result<String, String> {
    let asset = state.asset.lock().unwrap().clone().ok_or("请先检查更新")?;
    // NSIS 安装包和 macOS 的 dmg 由我们安装，放临时目录；其他的要用户自己处理，放「下载」文件夹
    let dir = if matches!(install_kind(), InstallKind::Nsis | InstallKind::MacApp) {
        std::env::temp_dir().join("FreeRead-update")
    } else {
        app.path().download_dir().map_err(|e| e.to_string())?
    };
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let dest = dir.join(&asset.name);
    let part = dir.join(format!("{}.part", asset.name));

    let mut resp = client()?
        .get(&asset.browser_download_url)
        .send()
        .await
        .and_then(|r| r.error_for_status())
        .map_err(|e| format!("下载失败：{e}"))?;
    let total = resp.content_length().unwrap_or(asset.size);
    let mut file = File::create(&part).map_err(|e| e.to_string())?;
    let mut hasher = Sha256::new();
    let (mut received, mut reported) = (0u64, 0u64);
    while let Some(chunk) = resp.chunk().await.map_err(|e| format!("下载中断：{e}"))? {
        file.write_all(&chunk).map_err(|e| e.to_string())?;
        hasher.update(&chunk);
        received += chunk.len() as u64;
        // 每 1% 报一次，免得事件刷屏
        if received - reported >= total / 100 || received == total {
            reported = received;
            let _ = app.emit("update-progress", Progress { received, total });
        }
    }
    drop(file);

    let sha = format!("{:x}", hasher.finalize());
    let bad = if received != asset.size {
        Some(format!("大小不符（{received} / {} 字节）", asset.size))
    } else {
        asset
            .digest
            .as_deref()
            .and_then(|d| d.strip_prefix("sha256:"))
            .filter(|want| !want.eq_ignore_ascii_case(&sha))
            .map(|_| "sha256 校验失败".to_owned())
    };
    if let Some(reason) = bad {
        let _ = std::fs::remove_file(&part);
        return Err(format!("下载的文件不完整：{reason}"));
    }
    let _ = std::fs::remove_file(&dest);
    std::fs::rename(&part, &dest).map_err(|e| e.to_string())?;
    #[cfg(unix)]
    if install_kind() == InstallKind::AppImage {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&dest, std::fs::Permissions::from_mode(0o755))
            .map_err(|e| e.to_string())?;
    }
    *state.downloaded.lock().unwrap() = Some(dest.clone());
    Ok(dest.display().to_string())
}

/// 安装版：运行安装包并退出（退出时照常关掉 sidecar）；macOS：用 dmg 里的新版替换当前的 .app，
/// 退出后重新打开；便携版、AppImage、deb / rpm：在文件管理器里显示下载的包。
#[tauri::command]
pub fn apply_update(app: AppHandle, state: State<'_, UpdateState>) -> Result<(), String> {
    let path = state
        .downloaded
        .lock()
        .unwrap()
        .clone()
        .ok_or("请先下载更新")?;
    if path.extension().is_some_and(|e| e == "exe") {
        std::process::Command::new(&path)
            .args(["/P", "/UPDATE", "/R"])
            .spawn()
            .map_err(|e| format!("无法启动安装程序：{e}"))?;
        app.exit(0);
        return Ok(());
    }
    #[cfg(target_os = "macos")]
    if path.extension().is_some_and(|e| e == "dmg") {
        let bundle = macos::current_bundle().ok_or("找不到当前的 FreeRead.app")?;
        return match macos::install_from_dmg(&path, &bundle) {
            Ok(old) => {
                macos::relaunch_after_exit(&bundle, &old)?;
                app.exit(0);
                Ok(())
            }
            // 装不上（例如没有写入「应用程序」文件夹的权限）时退回手动安装：在 Finder 里显示 dmg
            Err(e) => {
                let _ = reveal(&path);
                Err(format!(
                    "{e}。已在 Finder 中显示安装包，可以退出 FreeRead 后手动拖进“应用程序”替换"
                ))
            }
        };
    }
    reveal(&path)
}

/// macOS 的自动更新：挂载 dmg，把里面的 .app 复制到当前 .app 旁边，两者换名，退出后重新打开。
/// dmg 由我们自己下载，没有隔离属性（quarantine），换上去的新版打开时不会再弹 Gatekeeper 提示。
#[cfg(target_os = "macos")]
mod macos {
    use std::path::{Path, PathBuf};
    use std::process::{Command, Stdio};

    /// 当前运行的 `.app`：可执行文件在 `<X>.app/Contents/MacOS/` 里时返回 `<X>.app`。
    pub fn current_bundle() -> Option<PathBuf> {
        let exe = std::env::current_exe().ok()?;
        bundle_of(&exe)
    }

    pub(super) fn bundle_of(exe: &Path) -> Option<PathBuf> {
        let macos_dir = exe.parent()?;
        let contents = macos_dir.parent()?;
        let bundle = contents.parent()?;
        (macos_dir.file_name()? == "MacOS"
            && contents.file_name()? == "Contents"
            && bundle.extension()? == "app")
            .then(|| bundle.to_path_buf())
    }

    fn run(cmd: &mut Command, what: &str) -> Result<(), String> {
        let out = cmd
            .stdin(Stdio::null())
            .output()
            .map_err(|e| format!("{what}失败：{e}"))?;
        if out.status.success() {
            Ok(())
        } else {
            Err(format!(
                "{what}失败：{}",
                String::from_utf8_lossy(&out.stderr).trim()
            ))
        }
    }

    /// 退出时卸载 dmg。
    struct Mounted(PathBuf);

    impl Drop for Mounted {
        fn drop(&mut self) {
            let _ = Command::new("hdiutil")
                .args(["detach", "-quiet", "-force"])
                .arg(&self.0)
                .output();
            let _ = std::fs::remove_dir(&self.0);
        }
    }

    /// 用 `dmg` 里的新版替换 `bundle`，返回换下来的旧版路径（退出后删掉）。
    /// 失败时 `bundle` 保持原样。
    pub fn install_from_dmg(dmg: &Path, bundle: &Path) -> Result<PathBuf, String> {
        let path_str = bundle.to_string_lossy();
        // 从 dmg 里直接打开、或者没拖出「下载」文件夹就打开时，系统在只读的随机目录里运行
        // （App Translocation / 挂载的 dmg），替换不了
        if path_str.contains("/AppTranslocation/") || path_str.starts_with("/Volumes/") {
            return Err("FreeRead 不是从“应用程序”等文件夹里运行的，无法自动替换".into());
        }
        let parent = bundle.parent().ok_or("找不到 FreeRead.app 所在的文件夹")?;
        let name = bundle
            .file_name()
            .ok_or("找不到 FreeRead.app")?
            .to_string_lossy();
        let staged = parent.join(format!(".{name}.update"));
        let old = parent.join(format!(".{name}.old"));

        for leftover in [&staged, &old] {
            if leftover.exists() {
                std::fs::remove_dir_all(leftover)
                    .map_err(|e| format!("清理上次更新的残留失败：{e}"))?;
            }
        }
        // 先试着在旁边建目录：标准用户没有写入「应用程序」的权限，这时不必挂载 dmg
        match std::fs::create_dir(&staged) {
            Ok(()) => {
                let _ = std::fs::remove_dir(&staged);
            }
            Err(e) if e.kind() == std::io::ErrorKind::PermissionDenied => {
                return Err(format!(
                    "没有写入“{}”的权限，无法自动替换",
                    parent.display()
                ));
            }
            Err(e) => return Err(format!("无法写入“{}”：{e}", parent.display())),
        }

        let mount =
            std::env::temp_dir().join(format!("FreeRead-update-mnt-{}", std::process::id()));
        std::fs::create_dir_all(&mount).map_err(|e| e.to_string())?;
        if let Err(e) = run(
            Command::new("hdiutil")
                .args([
                    "attach",
                    "-nobrowse",
                    "-readonly",
                    "-noautoopen",
                    "-mountpoint",
                ])
                .arg(&mount)
                .arg(dmg),
            "挂载安装包",
        ) {
            let _ = std::fs::remove_dir(&mount);
            return Err(e);
        }
        let mounted = Mounted(mount);
        let new_app = std::fs::read_dir(&mounted.0)
            .map_err(|e| e.to_string())?
            .filter_map(Result::ok)
            .map(|e| e.path())
            .find(|p| p.extension().is_some_and(|e| e == "app"))
            .ok_or("安装包里没有 .app")?;

        // ditto 保留签名、扩展属性和符号链接
        if let Err(e) = run(
            Command::new("ditto").arg(&new_app).arg(&staged),
            "复制新版本",
        ) {
            let _ = std::fs::remove_dir_all(&staged);
            return Err(e);
        }
        drop(mounted);
        if let Err(e) = run(
            Command::new("codesign")
                .args(["--verify", "--deep", "--strict"])
                .arg(&staged),
            "校验新版本的签名",
        ) {
            let _ = std::fs::remove_dir_all(&staged);
            return Err(e);
        }

        // 同一文件夹里换名是原子的；运行中的程序和 sidecar 按 inode 打开文件，不受影响
        std::fs::rename(bundle, &old).map_err(|e| {
            let _ = std::fs::remove_dir_all(&staged);
            format!("替换旧版本失败：{e}")
        })?;
        if let Err(e) = std::fs::rename(&staged, bundle) {
            let _ = std::fs::rename(&old, bundle);
            let _ = std::fs::remove_dir_all(&staged);
            return Err(format!("替换旧版本失败：{e}"));
        }
        Ok(old)
    }

    /// 起一个独立的 shell 等本进程退出，删掉旧版并打开新版。路径作为参数传入，不拼进脚本。
    pub fn relaunch_after_exit(bundle: &Path, old: &Path) -> Result<(), String> {
        Command::new("/bin/sh")
            .arg("-c")
            .arg(r#"while kill -0 "$1" 2>/dev/null; do sleep 0.2; done; rm -rf -- "$2"; open -- "$3""#)
            .arg("freeread-update")
            .arg(std::process::id().to_string())
            .arg(old)
            .arg(bundle)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .map(drop)
            .map_err(|e| format!("无法重新打开 FreeRead：{e}"))
    }
}

#[cfg(windows)]
fn reveal(path: &std::path::Path) -> Result<(), String> {
    use std::os::windows::process::CommandExt;
    // explorer 只认 `/select,"路径"` 这种写法，不能交给 std 按参数规则加引号
    std::process::Command::new("explorer")
        .raw_arg(format!("/select,\"{}\"", path.display()))
        .spawn()
        .map(drop)
        .map_err(|e| e.to_string())
}

/// 各家文件管理器选中文件的方式不统一，用 xdg-open 打开所在文件夹。
#[cfg(target_os = "linux")]
fn reveal(path: &std::path::Path) -> Result<(), String> {
    let dir = path.parent().unwrap_or(path);
    std::process::Command::new("xdg-open")
        .arg(dir)
        .spawn()
        .map(drop)
        .map_err(|e| format!("已保存到 {}（无法打开文件夹：{e}）", path.display()))
}

#[cfg(target_os = "macos")]
fn reveal(path: &std::path::Path) -> Result<(), String> {
    std::process::Command::new("open")
        .arg("-R")
        .arg(path)
        .spawn()
        .map(drop)
        .map_err(|e| format!("已保存到 {}（无法在 Finder 中显示：{e}）", path.display()))
}

#[cfg(not(any(windows, target_os = "linux", target_os = "macos")))]
fn reveal(path: &std::path::Path) -> Result<(), String> {
    Err(format!("已保存到 {}", path.display()))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn asset(name: &str) -> GhAsset {
        GhAsset {
            name: name.into(),
            size: 1,
            browser_download_url: String::new(),
            digest: None,
        }
    }

    #[test]
    fn compares_tag_with_current_version() {
        assert!(is_newer("v0.2.0", "0.1.0"));
        assert!(is_newer("0.1.1", "0.1.0"));
        assert!(!is_newer("v0.1.0", "0.1.0"));
        assert!(!is_newer("v0.1.0", "0.2.0"));
        assert!(!is_newer("nightly", "0.1.0"));
        assert!(!is_newer("v0.2.0-beta.1", "0.2.0"));
    }

    #[test]
    fn picks_asset_for_install_kind() {
        // 文件名与 tauri-bundler 的命名一致
        let assets = [
            asset("FreeRead_0.2.0_x64-portable.zip"),
            asset("FreeRead_0.2.0_x64-setup.exe"),
            asset("FreeRead_0.2.0_amd64.deb"),
            asset("FreeRead-0.2.0-1.x86_64.rpm"),
            asset("FreeRead_0.2.0_amd64.AppImage"),
            asset("FreeRead_0.2.0_aarch64.dmg"),
        ];
        let name = |kind| pick_asset(&assets, kind).map(|a| a.name.as_str());
        assert_eq!(
            name(InstallKind::Nsis),
            Some("FreeRead_0.2.0_x64-setup.exe")
        );
        assert_eq!(
            name(InstallKind::Portable),
            Some("FreeRead_0.2.0_x64-portable.zip")
        );
        assert_eq!(name(InstallKind::Deb), Some("FreeRead_0.2.0_amd64.deb"));
        assert_eq!(name(InstallKind::Rpm), Some("FreeRead-0.2.0-1.x86_64.rpm"));
        assert_eq!(
            name(InstallKind::AppImage),
            Some("FreeRead_0.2.0_amd64.AppImage")
        );
        assert_eq!(
            name(InstallKind::MacApp),
            Some("FreeRead_0.2.0_aarch64.dmg")
        );
        assert_eq!(name(InstallKind::Aur), None);
        assert_eq!(name(InstallKind::Unknown), None);
        assert!(pick_asset(&assets[..1], InstallKind::Nsis).is_none());
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn finds_app_bundle_of_executable() {
        use std::path::Path;
        assert_eq!(
            macos::bundle_of(Path::new(
                "/Applications/FreeRead.app/Contents/MacOS/freeread-desktop"
            )),
            Some("/Applications/FreeRead.app".into())
        );
        // 开发构建：target/release/freeread-desktop
        assert_eq!(
            macos::bundle_of(Path::new("/src/target/release/freeread-desktop")),
            None
        );
        assert_eq!(
            macos::bundle_of(Path::new("/x/Contents/MacOS/freeread-desktop")),
            None
        );
    }

    /// 真实替换一次：`FREEREAD_TEST_DMG` 指向打好的 dmg，`FREEREAD_TEST_APP` 指向一份可以被覆盖的 .app。
    /// `cargo test -- --ignored replaces_app_from_dmg`
    #[cfg(target_os = "macos")]
    #[test]
    #[ignore]
    fn replaces_app_from_dmg() {
        let dmg = std::env::var("FREEREAD_TEST_DMG").expect("FREEREAD_TEST_DMG");
        let app = PathBuf::from(std::env::var("FREEREAD_TEST_APP").expect("FREEREAD_TEST_APP"));
        let marker = app.join("Contents/old-marker");
        std::fs::write(&marker, "old").unwrap();
        let old = macos::install_from_dmg(std::path::Path::new(&dmg), &app).unwrap();
        assert!(!marker.exists(), "新版本里不应有旧版的标记文件");
        assert!(
            old.join("Contents/old-marker").exists(),
            "旧版本应该换名留着"
        );
        assert!(app.join("Contents/MacOS/freeread-desktop").is_file());
        assert!(
            app.join("Contents/Resources/freeread-core/freeread-core")
                .is_file()
        );
        std::fs::remove_dir_all(old).unwrap();
    }
}
