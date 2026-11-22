//! 原生界面风格（docs/adr/0011-native-style.md）要的系统信息：系统强调色、窗口材质是否可用。
//!
//! - 强调色：macOS 读 `NSColor.controlAccentColor`；Windows 读 `Explorer\Accent\AccentPalette`
//!   第 4 个颜色（即 WinUI 的 SystemAccentColor），读不到退到 `DWM\AccentColor`。
//! - 材质：macOS 的 NSVisualEffectView 总可用；Windows 的 Mica 要 Windows 11（build ≥ 22000），
//!   Windows 10 上 setEffects 不报错但没有效果，前端据此决定窗口底色要不要透明。
//! - Liquid Glass：macOS 26+（NSGlassEffectView）。判断条件与 window-vibrancy 的 apply_liquid_glass 一致
//!   （NSAppKitVersionNumber ≥ 2685），前端据此换成 macOS 26 的样式：整列玻璃侧栏、更圆的控件。

use serde::Serialize;

#[derive(Clone, Debug, Default, Serialize)]
pub struct NativeLook {
    /// `#RRGGBB`；读不到为 None，前端退回用户选的强调色。
    accent: Option<String>,
    /// 窗口材质（vibrancy / Mica）可用。
    material: bool,
    /// Liquid Glass（macOS 26+）可用；setEffects 传 LiquidGlassRegular 时 Tauri 会用它而不是 vibrancy。
    glass: bool,
}

#[tauri::command]
pub fn native_look() -> NativeLook {
    NativeLook {
        accent: imp::accent(),
        material: imp::material(),
        glass: imp::glass(),
    }
}

fn hex(r: u8, g: u8, b: u8) -> String {
    format!("#{r:02X}{g:02X}{b:02X}")
}

#[cfg(target_os = "macos")]
mod imp {
    use objc2_app_kit::{NSAppKitVersionNumber, NSColor, NSColorSpace};

    /// macOS 26.0 的 AppKit 版本号，与 window-vibrancy 的 MIN_APPKIT_VERSION_LIQUID_GLASS 相同。
    const APPKIT_MACOS_26: f64 = 2685.0;

    pub fn accent() -> Option<String> {
        let color = NSColor::controlAccentColor();
        let rgb = color.colorUsingColorSpace(&NSColorSpace::sRGBColorSpace())?;
        let c = |v: f64| (v.clamp(0.0, 1.0) * 255.0).round() as u8;
        Some(super::hex(c(rgb.redComponent()), c(rgb.greenComponent()), c(rgb.blueComponent())))
    }

    pub fn material() -> bool {
        true
    }

    pub fn glass() -> bool {
        // SAFETY: AppKit 导出的只读全局常量
        unsafe { NSAppKitVersionNumber >= APPKIT_MACOS_26 }
    }
}

#[cfg(windows)]
mod imp {
    use windows_sys::Win32::System::Registry::{
        HKEY, HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE, RRF_RT_REG_BINARY, RRF_RT_REG_DWORD, RRF_RT_REG_SZ,
        RegGetValueW,
    };

    fn wide(s: &str) -> Vec<u16> {
        s.encode_utf16().chain(std::iter::once(0)).collect()
    }

    /// 读一个注册表值到 `buf`，返回实际字节数。
    fn read(root: HKEY, key: &str, value: &str, flags: u32, buf: &mut [u8]) -> Option<usize> {
        let (key, value) = (wide(key), wide(value));
        let mut len = buf.len() as u32;
        // SAFETY: key / value 是以 0 结尾的 UTF-16；buf 长度如实传入 len
        let rc = unsafe {
            RegGetValueW(
                root,
                key.as_ptr(),
                value.as_ptr(),
                flags,
                std::ptr::null_mut(),
                buf.as_mut_ptr().cast(),
                &mut len,
            )
        };
        (rc == 0).then_some(len as usize)
    }

    pub fn accent() -> Option<String> {
        // AccentPalette：8 个 RGBA，下标 3 是 SystemAccentColor
        let mut palette = [0u8; 32];
        if read(
            HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Accent",
            "AccentPalette",
            RRF_RT_REG_BINARY,
            &mut palette,
        ) == Some(32)
        {
            return Some(super::hex(palette[12], palette[13], palette[14]));
        }
        // DWM AccentColor：DWORD，0xAABBGGRR
        let mut dword = [0u8; 4];
        read(HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM", "AccentColor", RRF_RT_REG_DWORD, &mut dword)?;
        let v = u32::from_le_bytes(dword);
        Some(super::hex(v as u8, (v >> 8) as u8, (v >> 16) as u8))
    }

    pub fn material() -> bool {
        let mut buf = [0u8; 64];
        let Some(len) = read(
            HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion",
            "CurrentBuildNumber",
            RRF_RT_REG_SZ,
            &mut buf,
        ) else {
            return false;
        };
        let units: Vec<u16> = buf[..len].chunks_exact(2).map(|c| u16::from_le_bytes([c[0], c[1]])).collect();
        String::from_utf16_lossy(&units)
            .trim_end_matches('\0')
            .parse::<u32>()
            .is_ok_and(|build| build >= 22000)
    }

    pub fn glass() -> bool {
        false
    }
}

#[cfg(not(any(target_os = "macos", windows)))]
mod imp {
    pub fn accent() -> Option<String> {
        None
    }

    pub fn material() -> bool {
        false
    }

    pub fn glass() -> bool {
        false
    }
}

#[cfg(test)]
mod tests {
    #[test]
    fn hex_is_uppercase_rrggbb() {
        assert_eq!(super::hex(0x0a, 0x84, 0xff), "#0A84FF");
    }
}
