import { Worker } from 'node:worker_threads';
import { join } from 'node:path';
import type { DocAnchorModel, AppErrorWire } from '@freeread/core';
import { AppError } from '@freeread/core';
import { createFileValidator } from '../ipc/validate';
import { fail } from '../infra/files';

const validate = createFileValidator<DocAnchorModel>('doc-anchor-model.schema.json');
export function extractPdf(path: string, signal: AbortSignal, onProgress: (progress: number) => void): Promise<DocAnchorModel> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) { reject(fail('FR-NOTE-004')); return; }
    const worker = new Worker(join(__dirname, 'pdf-worker.js'), { workerData: path });
    const abort = () => { void worker.terminate(); reject(fail('FR-NOTE-004')); };
    signal.addEventListener('abort', abort, { once: true });
    worker.on('message', (message: { model?: unknown; error?: AppErrorWire; progress?: number }) => {
      if (message.progress !== undefined) { onProgress(message.progress); return; }
      signal.removeEventListener('abort', abort);
      void worker.terminate();
      if (message.error) { reject(AppError.fromWire(message.error)); return; }
      const result = validate.safeParse(message.model);
      if (result.success) resolve(result.data); else reject(fail('FR-LIB-002'));
    });
    worker.on('error', (cause) => { signal.removeEventListener('abort', abort); reject(fail('FR-LIB-002', cause)); });
    worker.on('exit', (code) => { if (code !== 0 && !signal.aborted) reject(fail('FR-LIB-002')); });
  });
}
