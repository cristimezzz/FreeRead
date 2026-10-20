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
    /** 服务端返回的原始 detail（可能是对象，如 {code, message, provider_id}） */
    readonly detail?: unknown,
  ) {
    super(message);
  }
}

/** 调用大模型前的检查失败（409）：未配置、缺密钥、需要隐私确认。不是这类错误时返回 null。 */
export function preflightError(e: unknown): { code: string; message: string; provider_id?: string | null } | null {
  if (!(e instanceof ApiError) || e.status !== 409) return null;
  const d = e.detail as { code?: unknown; message?: unknown } | undefined;
  return d && typeof d === "object" && typeof d.code === "string" ? (d as never) : null;
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
    throw new ApiError(result.response.status, detail || `HTTP ${result.response.status}`, e?.detail);
  }
  return result.data;
}
