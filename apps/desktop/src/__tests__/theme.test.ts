import { describe, expect, it } from "vitest";
import { resolveLook, themeVars } from "../app/theme";

describe("native style (ADR-0011)", () => {
  it("resolves the look per platform; Linux falls back to freeread", () => {
    expect(resolveLook("native", "mac")).toBe("mac");
    expect(resolveLook("native", "win")).toBe("win");
    expect(resolveLook("native", "linux")).toBe("freeread");
    expect(resolveLook("freeread", "mac")).toBe("freeread");
  });

  it("writes contrast overrides to native tokens instead of the warm freeread scale", () => {
    const freeread = themeVars("#0A84FF", false, "high");
    const mac = themeVars("#0A84FF", false, "high", "mac");
    expect(freeread["--border"]).toBeDefined();
    expect(mac["--border"]).toBeUndefined();
    expect(mac["--native-separator"]).toBeDefined();
    expect(mac["--muted-foreground"]).not.toBe(freeread["--muted-foreground"]);
    expect(themeVars("#0A84FF", true, "medium", "win")["--native-stroke"]).toMatch(/255 255 255/);
  });

  it("keeps the accent and standard contrast unchanged", () => {
    const v = themeVars("#0A84FF", false, "standard", "win");
    expect(v["--brand"]).toBe("#0A84FF");
    expect(v["--native-separator"]).toBeUndefined();
  });
});
