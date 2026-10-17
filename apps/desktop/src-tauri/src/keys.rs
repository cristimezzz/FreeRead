//! LLM API Key 的持久化：系统钥匙串里一个条目（service `FreeRead`，user `llm-keys`），
//! 值为 `{provider_id: key}` JSON。启动 sidecar 时整体读出，以环境变量 `FREEREAD_SECRETS`
//! 注入；Python 端只放内存。见 docs/01-architecture.md §5.4。
//!
//! 前端改密钥时先调 `set_api_key` / `delete_api_key` 写钥匙串，再调 Core 的
//! `PUT/DELETE /llm/providers/{id}/key` 让运行中的 sidecar 生效。
//!
//! 注意：Windows 凭据管理器单个条目上限 2560 字节（UTF-16 约 1280 字符），够存十来个 key。

use std::collections::BTreeMap;
use std::sync::Mutex;

const SERVICE: &str = "FreeRead";
const USER: &str = "llm-keys";
pub const ENV_VAR: &str = "FREEREAD_SECRETS";

pub type KeyMap = BTreeMap<String, String>;

/// 读-改-写整个 JSON，需串行化。
static WRITE_LOCK: Mutex<()> = Mutex::new(());

/// 错误信息只描述原因，绝不包含密钥内容。
fn describe(err: keyring::Error) -> String {
    match err {
        keyring::Error::BadEncoding(_) | keyring::Error::BadDataFormat(..) => {
            "keychain entry is not valid text".into()
        }
        keyring::Error::TooLong(..) => "too many API keys for one keychain entry".into(),
        other => format!("keychain: {other}"),
    }
}

fn entry() -> Result<keyring::Entry, String> {
    keyring::Entry::new(SERVICE, USER).map_err(describe)
}

/// 与 core 的 ProviderConfig.id 规则一致：`^[a-z0-9][a-z0-9_-]{0,31}$`。
fn valid_provider_id(id: &str) -> bool {
    let mut chars = id.chars();
    matches!(chars.next(), Some(c) if c.is_ascii_lowercase() || c.is_ascii_digit())
        && id.len() <= 32
        && chars.all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_' || c == '-')
}

pub fn load() -> Result<KeyMap, String> {
    match entry()?.get_password() {
        Ok(json) => serde_json::from_str(&json)
            .map_err(|_| "keychain entry is not a JSON object of strings".into()),
        Err(keyring::Error::NoEntry) => Ok(KeyMap::new()),
        Err(e) => Err(describe(e)),
    }
}

fn save(map: &KeyMap) -> Result<(), String> {
    let entry = entry()?;
    if map.is_empty() {
        return match entry.delete_credential() {
            Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
            Err(e) => Err(describe(e)),
        };
    }
    let json = serde_json::to_string(map).map_err(|e| format!("serialize keys: {e}"))?;
    entry.set_password(&json).map_err(describe)
}

fn update(provider_id: &str, f: impl FnOnce(&mut KeyMap)) -> Result<(), String> {
    if !valid_provider_id(provider_id) {
        return Err("invalid provider id".into());
    }
    let _guard = WRITE_LOCK.lock().unwrap_or_else(|e| e.into_inner());
    let mut map = load()?;
    f(&mut map);
    save(&map)
}

/// 环境变量值；钥匙串为空或读取失败时返回 None（失败原因写到 stderr，不含密钥）。
pub fn env_value() -> Option<String> {
    match load() {
        Ok(map) if map.is_empty() => None,
        Ok(map) => serde_json::to_string(&map).ok(),
        Err(e) => {
            eprintln!("[shell] load API keys failed: {e}");
            None
        }
    }
}

#[tauri::command]
pub async fn set_api_key(provider_id: String, key: String) -> Result<(), String> {
    let key = key.trim().to_owned();
    if key.is_empty() {
        return Err("empty API key".into());
    }
    tauri::async_runtime::spawn_blocking(move || {
        update(&provider_id, |map| {
            map.insert(provider_id.clone(), key);
        })
    })
    .await
    .map_err(|e| format!("keychain task failed: {e}"))?
}

#[tauri::command]
pub async fn delete_api_key(provider_id: String) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || {
        update(&provider_id, |map| {
            map.remove(&provider_id);
        })
    })
    .await
    .map_err(|e| format!("keychain task failed: {e}"))?
}

#[cfg(test)]
mod tests {
    use super::valid_provider_id;

    #[test]
    fn provider_id_rules() {
        for ok in ["deepseek", "openai-2", "a", "x_y", "0abc"] {
            assert!(valid_provider_id(ok), "{ok}");
        }
        for bad in ["", "-a", "Upper", "a b", "a/b", &"a".repeat(33)] {
            assert!(!valid_provider_id(bad), "{bad}");
        }
    }
}
