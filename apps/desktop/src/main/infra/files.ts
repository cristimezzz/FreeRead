import { openSync, writeFileSync, fsyncSync, closeSync, renameSync, unlinkSync, mkdirSync,
  readFileSync, realpathSync, existsSync, fstatSync, readSync } from 'node:fs';
import { dirname, relative, isAbsolute, resolve, join } from 'node:path';
import { randomBytes } from 'node:crypto';
import { AppError } from '@freeread/core';
import type { AppErrorWire } from '@freeread/core';

export function fail(code: AppErrorWire['code'], cause?: unknown): AppError {
  return new AppError(code, { category: code.startsWith('FR-IPC') ? 'ipc' : 'storage',
    severity: 'error', retryable: false, i18nKey: `errors.${code}`, cause });
}
export function ioError(cause: unknown): AppError {
  if (cause instanceof AppError) return cause;
  const code = typeof cause === 'object' && cause !== null ? Reflect.get(cause, 'code') : '';
  return fail(code === 'ENOSPC' ? 'FR-STORE-001' : code === 'EACCES' || code === 'EPERM'
    ? 'FR-STORE-002' : code === 'ENOENT' ? 'FR-LIB-005' : 'FR-STORE-012', cause);
}
export function ulid(): string {
  const alphabet = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';
  let time = Date.now(), prefix = '';
  for (let i = 0; i < 10; i++) { prefix = alphabet[time % 32] + prefix; time = Math.floor(time / 32); }
  return prefix + [...randomBytes(16)].map((b) => alphabet[b % 32]).join('');
}
export function atomicWrite(target: string, bytes: string | Uint8Array): void {
  const tmp = `${target}.tmp-${ulid()}`;
  try {
    const fd = openSync(tmp, 'wx');
    try { writeFileSync(fd, bytes); fsyncSync(fd); } finally { closeSync(fd); }
    renameSync(tmp, target);
    if (process.platform !== 'win32') {
      const dir = openSync(dirname(target), 'r');
      try { fsyncSync(dir); } finally { closeSync(dir); }
    }
  } catch (cause) {
    if (existsSync(tmp)) unlinkSync(tmp);
    throw ioError(cause);
  }
}
export function appendDurable(target: string, value: unknown): void {
  try {
    const fd = openSync(target, 'a+');
    try {
      const size = fstatSync(fd).size, tail = Buffer.alloc(1);
      if (size) readSync(fd, tail, 0, 1, size - 1);
      if (size && tail[0] !== 10) writeFileSync(fd, '\n');
      writeFileSync(fd, JSON.stringify(value) + '\n'); fsyncSync(fd);
    } finally { closeSync(fd); }
  } catch (cause) { throw ioError(cause); }
}
export function contained(root: string, path: string): string {
  const actualRoot = realpathSync(root), actual = realpathSync(resolve(root, path));
  const rel = relative(actualRoot, actual);
  if (!rel || rel.startsWith('..') || isAbsolute(rel)) throw fail('FR-IPC-002');
  return actual;
}
export function ensureDirectory(path: string): void { mkdirSync(path, { recursive: true }); }
export function readJson(path: string): unknown {
  try { return JSON.parse(readFileSync(path, 'utf8')); } catch (cause) { throw ioError(cause); }
}
export function docPath(root: string, citekey: string, file: string): string {
  if (!/^[a-z0-9][a-z0-9-]{0,39}$/.test(citekey)) throw fail('FR-IPC-002');
  return join(root, citekey, file);
}
export function installationId(dataDir: string): string {
  const path = join(dataDir, '.device-id');
  if (existsSync(path)) {
    const id = readFileSync(path, 'utf8').trim();
    if (!/^dev_[0-9A-HJKMNP-TV-Z]{26}$/.test(id)) throw fail('FR-STORE-008');
    return id;
  }
  const id = `dev_${ulid()}`; atomicWrite(path, id + '\n'); return id;
}
