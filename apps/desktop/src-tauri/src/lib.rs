//! FreeRead 桌面壳：启动 / 关闭 `freeread-core` sidecar，把端口和会话 token 交给前端。
//! 见 docs/01-architecture.md §3 与 docs/adr/0001-tauri-python-sidecar.md。
//!
//! sidecar 是 PyInstaller onedir 目录（scripts/build_sidecar.ps1），经 `bundle.resources`
//! 安装到 `<resource_dir>/freeread-core/`；`externalBin` 只能带单个可执行文件，所以不用它。
//!
//! sidecar 退出清理有三道保险：
//! 1. `RunEvent::Exit` 时主动结束子进程（正常关闭）；
//! 2. Windows 上子进程放进 KILL_ON_JOB_CLOSE 的 Job Object（壳崩溃 / 被强杀）；
//! 3. sidecar 自身的 `--parent-pid` 看门狗（core/freeread/main.py）。

#[cfg(windows)]
mod job;
mod keys;

use std::net::TcpListener;
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

use serde::Serialize;
use tauri::{Manager, RunEvent};
use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct CoreInfo {
    port: u16,
    token: String,
    /// sidecar 启动时刻（Unix 毫秒），前端据此显示启动到 /health 可用的耗时。
    spawned_at_ms: u64,
}

struct Sidecar {
    info: CoreInfo,
    child: Mutex<Option<CommandChild>>,
    #[cfg(windows)]
    job: Option<job::Job>,
}

impl Sidecar {
    fn shutdown(&self) {
        if let Some(child) = self.child.lock().unwrap().take() {
            let _ = child.kill();
        }
        // 兜底：sidecar 自己派生的子进程（如 MinerU worker）kill 主进程不会带走。
        #[cfg(windows)]
        if let Some(job) = &self.job {
            job.terminate();
        }
    }
}

/// sidecar 启动失败时窗口照常打开，把原因显示给用户（例如被杀毒软件拦截）。
struct SpawnError(String);

#[tauri::command]
fn core_info(app: tauri::AppHandle) -> Result<CoreInfo, String> {
    if let Some(sidecar) = app.try_state::<Sidecar>() {
        return Ok(sidecar.info.clone());
    }
    Err(app
        .try_state::<SpawnError>()
        .map_or_else(|| "sidecar not started".into(), |e| e.0.clone()))
}

fn free_port() -> std::io::Result<u16> {
    Ok(TcpListener::bind(("127.0.0.1", 0))?.local_addr()?.port())
}

fn random_token() -> String {
    let mut bytes = [0u8; 32];
    getrandom::fill(&mut bytes).expect("OS random number generator unavailable");
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// `<resource_dir>/freeread-core/freeread-core[.exe]`。`tauri dev` 时 resource_dir 是
/// target/debug，tauri-build 会把 binaries/freeread-core/ 复制过去（需先运行 build_sidecar.ps1）。
fn core_exe(app: &tauri::AppHandle) -> tauri::Result<PathBuf> {
    Ok(app
        .path()
        .resource_dir()?
        .join("freeread-core")
        .join(format!("freeread-core{}", std::env::consts::EXE_SUFFIX)))
}

fn spawn_core(app: &tauri::AppHandle) -> Result<Sidecar, Box<dyn std::error::Error>> {
    let port = free_port().map_err(|e| format!("allocate port: {e}"))?;
    let token = random_token();

    #[cfg(windows)]
    let job = job::Job::new_kill_on_close()
        .inspect_err(|e| eprintln!("[shell] create job object failed: {e}"))
        .ok();

    let exe = core_exe(app)?;
    if !exe.is_file() {
        return Err(format!("sidecar not found: {}", exe.display()).into());
    }
    let mut command = app.shell().command(&exe);
    // API Key 只经环境变量交给 sidecar，不出现在命令行参数里（进程列表可见）。
    if let Some(secrets) = keys::env_value() {
        command = command.env(keys::ENV_VAR, secrets);
    }
    let (mut rx, child) = command
        .args([
            "--port",
            &port.to_string(),
            "--token",
            &token,
            "--parent-pid",
            &std::process::id().to_string(),
        ])
        .spawn()
        .map_err(|e| format!("spawn freeread-core: {e}"))?;
    let spawned_at_ms = SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis() as u64;

    // 尽早放进 job：之后 sidecar 派生的子进程（如 MinerU worker）自动继承 job。
    #[cfg(windows)]
    if let Some(job) = &job
        && let Err(e) = job.assign_pid(child.pid())
    {
        eprintln!("[shell] assign sidecar to job failed: {e}");
    }

    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) | CommandEvent::Stderr(line) => {
                    eprintln!("[core] {}", String::from_utf8_lossy(&line).trim_end());
                }
                CommandEvent::Terminated(payload) => {
                    eprintln!("[core] exited with {:?}", payload.code);
                }
                _ => {}
            }
        }
    });

    Ok(Sidecar {
        info: CoreInfo {
            port,
            token,
            spawned_at_ms,
        },
        child: Mutex::new(Some(child)),
        #[cfg(windows)]
        job,
    })
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            match spawn_core(app.handle()) {
                Ok(sidecar) => {
                    app.manage(sidecar);
                }
                Err(e) => {
                    eprintln!("[shell] {e}");
                    app.manage(SpawnError(e.to_string()));
                }
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            core_info,
            keys::set_api_key,
            keys::delete_api_key
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let RunEvent::Exit = event
                && let Some(sidecar) = app.try_state::<Sidecar>()
            {
                sidecar.shutdown();
            }
        });
}
