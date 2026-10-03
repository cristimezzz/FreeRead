import { parentPort, workerData } from 'node:worker_threads';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { getDocument } from 'pdfjs-dist/legacy/build/pdf.mjs';
import { z } from 'zod';
import { buildReadingModel, toAppError } from '@freeread/core';

async function extract() {
  const path = z.string().parse(workerData);
  const data = new Uint8Array(readFileSync(path));
  const docId = createHash('sha256').update(data).digest('hex');
  const task = getDocument({ data, useSystemFonts: true });
  const pdf = await task.promise;
  try {
    const pages = [];
    for (let page = 1; page <= pdf.numPages; page++) {
      const p = await pdf.getPage(page), viewport = p.getViewport({ scale: 1 });
      const content = await p.getTextContent();
      const lines = content.items.flatMap((item) => {
        if (!('str' in item)) return [];
        const [x = 0, y = 0] = viewport.convertToViewportPoint(item.transform[4] ?? 0, item.transform[5] ?? 0);
        return [{ text: item.str, rect: { x: Math.max(0, x), y: Math.max(0, y - item.height),
          w: Math.abs(item.width), h: Math.abs(item.height) } }];
      });
      pages.push({ w: viewport.width, h: viewport.height, lines });
      parentPort?.postMessage({ progress: page / pdf.numPages });
      p.cleanup();
    }
    parentPort?.postMessage({ model: buildReadingModel({ docId, pages }) });
  } finally { await task.destroy(); }
}
extract().catch((cause: unknown) => parentPort?.postMessage({ error: toAppError(cause, 'FR-LIB-002').toWire() }));
