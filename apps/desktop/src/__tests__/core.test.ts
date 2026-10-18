import { afterEach, describe, expect, it, vi } from "vitest";
import { CoreExitedError, waitForHealth, type CoreExit, type CoreExitSource } from "../api/core";

const info = { baseUrl: "http://127.0.0.1:1", token: "t" };
const crash: CoreExit = { code: 3, signal: null, stderrTail: ["Traceback", "ImportError: boom"] };

/** 可手动触发的退出事件源；`already` 模拟订阅前就已退出（core_status 有值）。 */
function fakeExits(already?: CoreExit) {
  let emit: ((exit: CoreExit) => void) | undefined;
  const off = vi.fn();
  const source: CoreExitSource = async (onExit) => {
    emit = onExit;
    if (already) onExit(already);
    return off;
  };
  return { source, off, fire: (exit: CoreExit) => emit?.(exit) };
}

const refused = () => Promise.reject(new TypeError("fetch failed"));

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("waitForHealth", () => {
  it("rejects with the exit info as soon as the sidecar terminates", async () => {
    const fetchMock = vi.fn(refused);
    vi.stubGlobal("fetch", fetchMock);
    const exits = fakeExits();
    const started = Date.now();
    const p = waitForHealth(info, { exits: exits.source, timeoutMs: 30_000 });
    setTimeout(() => exits.fire(crash), 250);
    const err = await p.catch((e: unknown) => e);
    expect(err).toBeInstanceOf(CoreExitedError);
    expect((err as CoreExitedError).exit).toEqual(crash);
    expect((err as Error).message).toContain("退出码 3");
    expect(Date.now() - started).toBeLessThan(2_000);
    expect(exits.off).toHaveBeenCalled();
    // 退出后不再继续轮询
    const calls = fetchMock.mock.calls.length;
    await new Promise((r) => setTimeout(r, 300));
    expect(fetchMock.mock.calls.length).toBeLessThanOrEqual(calls + 1);
  });

  it("rejects immediately when the sidecar had already exited before subscribing", async () => {
    const fetchMock = vi.fn(refused);
    vi.stubGlobal("fetch", fetchMock);
    await expect(waitForHealth(info, { exits: fakeExits(crash).source })).rejects.toBeInstanceOf(CoreExitedError);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("resolves once /health is ok and ignores a later exit", async () => {
    let n = 0;
    vi.stubGlobal("fetch", () => (++n < 3 ? refused() : Promise.resolve(new Response("{}"))));
    const exits = fakeExits();
    await expect(waitForHealth(info, { exits: exits.source })).resolves.toBeUndefined();
    expect(exits.off).toHaveBeenCalled();
    exits.fire(crash); // 不应产生未处理的 rejection
  });

  it("still fails fast on HTTP errors and times out without an exit source (browser mode)", async () => {
    vi.stubGlobal("fetch", () => Promise.resolve(new Response("", { status: 401 })));
    await expect(waitForHealth(info, { exits: fakeExits().source })).rejects.toThrow("HTTP 401");
    vi.stubGlobal("fetch", refused);
    await expect(waitForHealth(info, { timeoutMs: 200 })).rejects.toThrow("未就绪");
  });

  it("falls back to polling when subscribing fails", async () => {
    vi.stubGlobal("fetch", () => Promise.resolve(new Response("{}")));
    const broken: CoreExitSource = () => Promise.reject(new Error("no ipc"));
    await expect(waitForHealth(info, { exits: broken })).resolves.toBeUndefined();
  });
});
