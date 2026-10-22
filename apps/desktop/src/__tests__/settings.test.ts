import { describe, expect, it } from "vitest";
import { engineOptionLabel, urlHost } from "../features/settings/SettingsView";
import { avatarSrc, formatDate, formatSize, plainNotes } from "../features/settings/about";

const engine = { name: "mineru", label: "MinerU", available: true, heavy: true, location: "local" as const, has_key: false };

describe("解析引擎下拉标签", () => {
  it("本机可用时只显示名称", () => {
    expect(engineOptionLabel(engine)).toBe("MinerU");
  });
  it("API 模式加注，不可用时写明原因", () => {
    expect(engineOptionLabel({ ...engine, location: "api" })).toBe("MinerU（API）");
    expect(
      engineOptionLabel({ ...engine, location: "api", available: false, unavailable_reason: "consent_required" }),
    ).toBe("MinerU（API）（待确认上传）");
    expect(engineOptionLabel({ ...engine, available: false, unavailable_reason: "not_installed" })).toBe(
      "MinerU（未安装）",
    );
  });
});

describe("urlHost", () => {
  it("取主机名（含端口），非法地址原样返回", () => {
    expect(urlHost("https://mineru.net/api")).toBe("mineru.net");
    expect(urlHost("http://127.0.0.1:8000")).toBe("127.0.0.1:8000");
    expect(urlHost("not a url")).toBe("not a url");
  });
});

describe("关于：格式化", () => {
  it("文件大小：MB 保留一位小数，小文件按 KB", () => {
    expect(formatSize(58113542)).toBe("55.4 MB");
    expect(formatSize(2048)).toBe("2 KB");
    expect(formatSize(10)).toBe("1 KB");
  });
  it("发布日期取年月日，空值或非法时为空串", () => {
    expect(formatDate("2026-10-20T10:05:56")).toBe("2026-10-20");
    expect(formatDate(null)).toBe("");
    expect(formatDate("garbage")).toBe("");
  });
  it("头像地址追加两倍尺寸", () => {
    expect(avatarSrc("https://avatars.githubusercontent.com/u/1?v=4", 36)).toBe(
      "https://avatars.githubusercontent.com/u/1?v=4&s=72",
    );
    expect(avatarSrc("https://avatars.githubusercontent.com/u/1", 20)).toBe("https://avatars.githubusercontent.com/u/1?s=40");
  });
});

describe("关于：更新说明", () => {
  it("去掉 Markdown 标题和粗体标记，列表换成圆点", () => {
    expect(plainNotes("## 新功能\r\n- **关于**页\n  * 子项\n\n正文")).toBe("新功能\n· 关于页\n  · 子项\n\n正文");
  });
});
