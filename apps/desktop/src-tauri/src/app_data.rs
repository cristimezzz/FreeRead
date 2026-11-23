//! 设置页「删除应用数据」：统计与删除 Core 数据目录、清除钥匙串里的 API Key，然后重启应用。
//!
//! 数据库等文件被运行中的 sidecar 占用，所以删除在壳里做：先停 sidecar，再删，再重启。
//! 数据目录与 core/freeread/config.py 的 `default_data_dir()` 一致（壳启动 sidecar 时不传
//! `--data-dir`）：Windows `%APPDATA%\FreeRead`、macOS `~/Library/Application Support/FreeRead`、
//! Linux `$XDG_DATA_HOME/FreeRead`（默认 `~/.local/share/FreeRead`）。改那边时这里同步。

use std::path::{Path, PathBuf};
use std::time::Duration;

use serde::Serialize;
use tauri::Manager;

use crate::keys;

const APP_DIR_NAME: &str = "FreeRead";

/// 归入「本机解析引擎与模型」的数据目录子项（config.py 的 `DataPaths.engines` / `models`），
/// 其余都算「文献、笔记与设置」。
const ENGINE_ENTRIES: [&str; 2] = ["engines", "models"];

fn data_root(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    app.path()
        .data_dir()
        .map(|d| d.join(APP_DIR_NAME))
        .map_err(|e| format!("locate data directory: {e}"))
}

fn is_engine_entry(name: &std::ffi::OsStr) -> bool {
    ENGINE_ENTRIES.iter().any(|e| name == *e)
}

/// 按勾选从数据目录的直接子项里挑出要删的路径。
fn targets(entries: &[PathBuf], library: bool, engines: bool) -> Vec<PathBuf> {
    entries
        .iter()
        .filter(|p| {
            let engine = p.file_name().is_some_and(is_engine_entry);
            if engine { engines } else { library }
        })
        .cloned()
        .collect()
}

fn list_entries(root: &Path) -> Result<Vec<PathBuf>, String> {
    match std::fs::read_dir(root) {
        Ok(rd) => Ok(rd.filter_map(|e| e.ok().map(|e| e.path())).collect()),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(Vec::new()),
        Err(e) => Err(format!("read {}: {e}", root.display())),
    }
}

/// 递归求大小，不跟随符号链接；读不了的项跳过。
fn size_of(path: &Path) -> u64 {
    let Ok(meta) = std::fs::symlink_metadata(path) else {
        return 0;
    };
    if !meta.is_dir() {
        return meta.len();
    }
    std::fs::read_dir(path)
        .map(|rd| rd.filter_map(Result::ok).map(|e| size_of(&e.path())).sum())
        .unwrap_or(0)
}

fn remove(path: &Path) -> std::io::Result<()> {
    let meta = match std::fs::symlink_metadata(path) {
        Ok(m) => m,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(()),
        Err(e) => return Err(e),
    };
    let result = if meta.is_dir() {
        std::fs::remove_dir_all(path)
    } else {
        std::fs::remove_file(path)
    };
    match result {
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(()),
        other => other,
    }
}

/// sidecar 被结束后，Windows 上文件句柄要过一会儿才释放，删除失败时重试几秒。
fn remove_with_retry(path: &Path) -> std::io::Result<()> {
    const ATTEMPTS: u32 = 25;
    let mut last = Ok(());
    for i in 0..ATTEMPTS {
        last = remove(path);
        if last.is_ok() {
            break;
        }
        if i + 1 < ATTEMPTS {
            std::thread::sleep(Duration::from_millis(200));
        }
    }
    last
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Usage {
    root: String,
    library: u64,
    engines: u64,
}

#[tauri::command]
pub async fn app_data_usage(app: tauri::AppHandle) -> Result<Usage, String> {
    let root = data_root(&app)?;
    tauri::async_runtime::spawn_blocking(move || {
        let entries = list_entries(&root)?;
        let sum = |paths: Vec<PathBuf>| paths.iter().map(|p| size_of(p)).sum();
        Ok(Usage {
            library: sum(targets(&entries, true, false)),
            engines: sum(targets(&entries, false, true)),
            root: root.display().to_string(),
        })
    })
    .await
    .map_err(|e| format!("usage task failed: {e}"))?
}

/// 停掉 sidecar，按勾选删除，全部成功后重启应用；有失败时返回原因（sidecar 已停，前端再调
/// [`restart_app`]）。错误信息只含路径和系统错误，不含密钥。
#[tauri::command]
pub async fn delete_app_data(
    app: tauri::AppHandle,
    library: bool,
    keys: bool,
    engines: bool,
) -> Result<(), String> {
    if !(library || keys || engines) {
        return Err("nothing selected".into());
    }
    let root = data_root(&app)?;
    if let Some(sidecar) = app.try_state::<crate::Sidecar>() {
        sidecar.shutdown();
    }
    let errors = tauri::async_runtime::spawn_blocking(move || {
        let mut errors = Vec::new();
        match list_entries(&root) {
            Ok(entries) => {
                for path in targets(&entries, library, engines) {
                    if let Err(e) = remove_with_retry(&path) {
                        errors.push(format!("{}: {e}", path.display()));
                    }
                }
            }
            Err(e) => errors.push(e),
        }
        if keys && let Err(e) = keys::clear() {
            errors.push(e);
        }
        errors
    })
    .await
    .map_err(|e| format!("delete task failed: {e}"))?;
    if !errors.is_empty() {
        eprintln!("[shell] delete app data failed: {}", errors.join("; "));
        return Err(errors.join("\n"));
    }
    app.restart();
}

#[tauri::command]
pub fn restart_app(app: tauri::AppHandle) {
    app.restart();
}

#[cfg(test)]
mod tests {
    use super::*;

    fn entries() -> Vec<PathBuf> {
        let root = Path::new("data");
        [
            "freeread.db",
            "freeread.db-wal",
            "documents",
            "logs",
            "zotero-snapshots",
            "engines",
            "models",
        ]
        .iter()
        .map(|n| root.join(n))
        .collect()
    }

    fn names(paths: Vec<PathBuf>) -> Vec<String> {
        paths
            .iter()
            .map(|p| p.file_name().unwrap().to_string_lossy().into_owned())
            .collect()
    }

    #[test]
    fn library_keeps_engines_and_models() {
        assert_eq!(
            names(targets(&entries(), true, false)),
            [
                "freeread.db",
                "freeread.db-wal",
                "documents",
                "logs",
                "zotero-snapshots"
            ]
        );
    }

    #[test]
    fn engines_only() {
        assert_eq!(
            names(targets(&entries(), false, true)),
            ["engines", "models"]
        );
    }

    #[test]
    fn everything_or_nothing() {
        assert_eq!(targets(&entries(), true, true), entries());
        assert!(targets(&entries(), false, false).is_empty());
    }

    #[test]
    fn remove_handles_files_dirs_and_missing() {
        let dir =
            std::env::temp_dir().join(format!("freeread-app-data-test-{}", std::process::id()));
        std::fs::create_dir_all(dir.join("sub")).unwrap();
        std::fs::write(dir.join("sub/a.txt"), b"x").unwrap();
        std::fs::write(dir.join("b.txt"), b"yy").unwrap();
        assert_eq!(size_of(&dir), 3);
        remove(&dir.join("b.txt")).unwrap();
        remove(&dir.join("missing")).unwrap();
        remove(&dir).unwrap();
        assert!(!dir.exists());
    }
}
