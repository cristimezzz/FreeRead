import { describe, expect, it } from "vitest";
import { engineOptionLabel, urlHost } from "../features/settings/SettingsView";

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
