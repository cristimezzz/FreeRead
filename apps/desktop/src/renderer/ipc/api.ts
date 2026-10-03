import type { AppErrorWire } from '@freeread/core';
import type { ApiResult } from './client.generated';

export async function unwrap<T>(request: Promise<ApiResult<T>>): Promise<T> {
  const result = await request;
  if (!result.ok) throw result.error;
  return result.data;
}
export function errorKey(cause: unknown): string {
  const key = typeof cause === 'object' && cause !== null ? Reflect.get(cause, 'i18nKey') : undefined;
  if (typeof key === 'string') return key;
  const error = uiError('FR-UI-001'); console.error(error);
  return error.i18nKey;
}
export function uiError(code: AppErrorWire['code']): AppErrorWire {
  return { code, category: 'ui', severity: 'error', retryable: false, i18nKey: `errors.${code}`, message: code };
}
export function newId(): string {
  const alphabet = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';
  let time = Date.now(), prefix = '';
  for (let i = 0; i < 10; i++) { prefix = alphabet[time % 32] + prefix; time = Math.floor(time / 32); }
  return prefix + [...crypto.getRandomValues(new Uint8Array(16))].map((b) => alphabet[b % 32]).join('');
}
