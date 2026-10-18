// 类型化的 Core Service 客户端。类型由 docs/schemas/openapi.json 生成（npm run gen:api）。

import createClient, { type Middleware } from "openapi-fetch";
import type { components, paths } from "./schema";
import type { CoreInfo } from "./core";

export type Schemas = components["schemas"];
export type Api = ReturnType<typeof createClient<paths>>;

let current: { info: CoreInfo; api: Api } | null = null;

export function connect(info: CoreInfo): Api {
  const auth: Middleware = {
    onRequest({ request }) {
      request.headers.set("X-FreeRead-Token", info.token);
      return request;
    },
  };
  const api = createClient<paths>({ baseUrl: info.baseUrl });
  api.use(auth);
  current = { info, api };
  return api;
}

export function api(): Api {
  if (!current) throw new Error("Core Service 尚未连接");
  return current.api;
}

export function coreInfo(): CoreInfo {
  if (!current) throw new Error("Core Service 尚未连接");
  return current.info;
}

/** 不在 OpenAPI 里描述内容的接口（IR、PDF、图片、SSE）用这个，自动带上 token。 */
export async function rawFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const { baseUrl, token } = coreInfo();
  const headers = new Headers(init.headers);
  headers.set("X-FreeRead-Token", token);
  const resp = await fetch(`${baseUrl}${path}`, { ...init, headers });
  if (!resp.ok) throw new ApiError(resp.status, await errorDetail(resp));
  return resp;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function errorDetail(resp: Response): Promise<string> {
  try {
    const body = await resp.json();
    return typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
  } catch {
    return `HTTP ${resp.status}`;
  }
}

/** openapi-fetch 的结果：有 error 时抛出，否则返回 data。 */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.error !== undefined || result.data === undefined) {
    const e = result.error as { detail?: unknown } | undefined;
    const detail = typeof e?.detail === "string" ? e.detail : JSON.stringify(e?.detail ?? e ?? "");
    throw new ApiError(result.response.status, detail || `HTTP ${result.response.status}`);
  }
  return result.data;
}
