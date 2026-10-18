// 用 fetch 读 SSE：原生 EventSource 不能带 X-FreeRead-Token 头，也不支持 POST。

import { rawFetch } from "./client";

export interface SseEvent {
  event: string;
  data: unknown;
}

/** 把字节流切成 SSE 事件。注释行（": ping"）忽略；data 按 JSON 解析。 */
export function createSseParser(onEvent: (e: SseEvent) => void) {
  let buffer = "";
  return (chunk: string) => {
    buffer += chunk.replace(/\r\n/g, "\n");
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const raw = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      let event = "message";
      const data: string[] = [];
      for (const line of raw.split("\n")) {
        if (!line || line.startsWith(":")) continue;
        const colon = line.indexOf(":");
        const field = colon < 0 ? line : line.slice(0, colon);
        const value = colon < 0 ? "" : line.slice(colon + 1).replace(/^ /, "");
        if (field === "event") event = value;
        else if (field === "data") data.push(value);
      }
      if (data.length) onEvent({ event, data: JSON.parse(data.join("\n")) });
    }
  };
}

/** 读一个 SSE 响应直到结束或被中止。 */
export async function streamSse(
  path: string,
  init: RequestInit,
  onEvent: (e: SseEvent) => void,
): Promise<void> {
  const resp = await rawFetch(path, init);
  if (!resp.body) return;
  const parse = createSseParser(onEvent);
  const reader = resp.body.pipeThrough(new TextDecoderStream()).getReader();
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    parse(value);
  }
}
