; Tauri NSIS 安装器钩子（tauri.conf.json → bundle.windows.nsis.installerHooks）。
;
; 卸载页的「Delete the application data」勾选框，Tauri 模板只删 $APPDATA\${BUNDLEID} 和
; $LOCALAPPDATA\${BUNDLEID}（后者是 WebView2 数据 EBWebView）。FreeRead 的实际数据在别处，
; 这里补上，让勾选框说的和做的一致：
;   - Core 数据目录 %APPDATA%\FreeRead（core/freeread/config.py 的 default_data_dir）：
;     主库、文档、Zotero 快照、模型、应用内安装的解析引擎及其缓存、日志；
;   - 系统钥匙串里的 API Key（src/keys.rs：service `FreeRead`、user `llm-keys`，
;     keyring 在 Windows 上存成凭据管理器里目标名 `llm-keys.FreeRead` 的普通凭据）。
; 没勾选、静默卸载（/S，勾选框不出现）或更新时（/UPDATE）都不动。
;
; 两个路径可在 !include 前预先定义，只为测试时指向临时目录 / 临时凭据。

!ifndef FREEREAD_DATA_DIR
  !define FREEREAD_DATA_DIR "$APPDATA\FreeRead"
!endif
!ifndef FREEREAD_CREDENTIAL
  !define FREEREAD_CREDENTIAL "llm-keys.FreeRead"
!endif

!macro NSIS_HOOK_POSTUNINSTALL
  ${If} $DeleteAppDataCheckboxState = 1
  ${AndIf} $UpdateMode <> 1
    SetShellVarContext current
    RmDir /r "${FREEREAD_DATA_DIR}"
    ; CredDeleteW(TargetName, CRED_TYPE_GENERIC, 0)：条目不存在时返回 0，忽略即可
    System::Call 'advapi32::CredDeleteW(w "${FREEREAD_CREDENTIAL}", i 1, i 0) i .r0'
  ${EndIf}
!macroend
