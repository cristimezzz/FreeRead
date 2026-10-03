import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { homedir } from 'node:os';
import type { AppConfig } from '../config.generated';
import { createFileValidator } from '../ipc/validate';
import { atomicWrite, readJson, fail } from './files';

export function loadConfig(dataDir: string, isolated: boolean): AppConfig {
  const path = join(dataDir, 'config.json');
  if (existsSync(path)) {
    const result = createFileValidator<AppConfig>('app-config.schema.json').safeParse(readJson(path));
    if (!result.success) throw fail('FR-STORE-008');
    return result.data;
  }
  const config: AppConfig = { schemaVersion: 1, locale: 'zh-CN', theme: 'system',
    libraryPath: isolated ? join(dataDir, 'library') : join(homedir(), 'FreeRead', 'library'),
    cachePath: join(dataDir, 'cache') };
  atomicWrite(path, JSON.stringify(config, null, 2) + '\n');
  return config;
}
