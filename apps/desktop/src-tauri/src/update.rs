//! 检查与下载更新、列出贡献者：数据来自 GitHub 上的 Release 与仓库贡献者，只在设置页「关于」里用到。
//!
//! 不用 tauri-plugin-updater：它要签名密钥和 latest.json，而 Release 只附 NSIS 安装包和便携版 zip
//! （.github/workflows/desktop-build.yml）。下载完按 Release 资源自带的 sha256 校验。
//!
//! - 安装版（exe 旁边有 NSIS 的 uninstall.exe）：下载 `*-setup.exe` 到临时目录，以 `/P /UPDATE /R`
//!   运行（与 tauri-plugin-updater 相同：只显示进度、跳过重装询问、不删数据、装完重新打开），随即退出；
//! - 便携版：下载 `*-portable.zip` 到「下载」文件夹，在资源管理器里选中，由用户自己解压替换。

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
    portable: bool,
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

/// 有 NSIS 卸载程序的是安装版，否则是便携版 zip 解压出来的。
fn is_portable() -> bool {
    std::env::current_exe()
        .map(|exe| !exe.with_file_name("uninstall.exe").is_file())
        .unwrap_or(true)
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

fn pick_asset(assets: &[GhAsset], portable: bool) -> Option<&GhAsset> {
    let suffix = if portable {
        "-portable.zip"
    } else {
        "-setup.exe"
    };
    assets.iter().find(|a| a.name.ends_with(suffix))
}

#[tauri::command]
pub async fn check_update(
    app: AppHandle,
    state: State<'_, UpdateState>,
) -> Result<UpdateInfo, String> {
    let release: GhRelease = github_json("releases/latest").await?;
    let current = app.package_info().version.to_string();
    let portable = is_portable();
    let asset = pick_asset(&release.assets, portable).cloned();
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
        portable,
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
    let dir = if is_portable() {
        app.path().download_dir().map_err(|e| e.to_string())?
    } else {
        std::env::temp_dir().join("FreeRead-update")
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
    *state.downloaded.lock().unwrap() = Some(dest.clone());
    Ok(dest.display().to_string())
}

/// 安装版：运行安装包并退出（退出时照常关掉 sidecar）；便携版：在资源管理器里选中下载的 zip。
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
    reveal(&path)
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

#[cfg(not(windows))]
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
        let assets = [
            asset("FreeRead_0.2.0_x64-portable.zip"),
            asset("FreeRead_0.2.0_x64-setup.exe"),
        ];
        assert_eq!(
            pick_asset(&assets, false).unwrap().name,
            "FreeRead_0.2.0_x64-setup.exe"
        );
        assert_eq!(
            pick_asset(&assets, true).unwrap().name,
            "FreeRead_0.2.0_x64-portable.zip"
        );
        assert!(pick_asset(&assets[..1], false).is_none());
    }
}
