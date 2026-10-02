import { createReadStream, statSync } from 'node:fs';
import { Readable } from 'node:stream';
import { protocol } from 'electron';
import type { LibraryService } from '../services/library-service';
import { contained, fail, ioError } from './files';

function authorizedUrl(request: Request): URL {
  const url = new URL(request.url);
  if (!/^[0-9a-f]{64}$/.test(url.hostname) || url.pathname !== '/paper.pdf' || url.search || url.username
    || !['GET', 'HEAD'].includes(request.method)) throw fail('FR-IPC-002');
  return url;
}
function byteRange(range: string | null, size: number) {
  const match = range?.match(/^bytes=(\d+)-(\d*)$/);
  const start = match ? Number(match[1]) : 0;
  const end = match?.[2] ? Math.min(Number(match[2]), size - 1) : size - 1;
  return { start, end, partial: !!match, invalid: !!(range && !match) || start > end || start >= size };
}

export function servePdf(library: LibraryService) {
  protocol.handle('fr-file', (request) => {
    try {
      const url = authorizedUrl(request);
      const path = contained(library.root, library.path(url.hostname, 'paper.pdf'));
      const size = statSync(path).size;
      const range = request.headers.get('range');
      const { start, end, partial, invalid } = byteRange(range, size);
      if (invalid) return new Response(null,
        { status: 416, headers: { 'Content-Range': `bytes */${size}` } });
      const headers = new Headers({ 'Content-Type': 'application/pdf', 'Accept-Ranges': 'bytes',
        'Content-Length': String(end - start + 1), 'Access-Control-Allow-Origin': '*', 'Cache-Control': 'no-store' });
      if (partial) headers.set('Content-Range', `bytes ${start}-${end}/${size}`);
      const stream = request.method === 'HEAD' ? null
        : Readable.toWeb(createReadStream(path, { start, end })) as ReadableStream<Uint8Array>;
      return new Response(stream, { status: partial ? 206 : 200, headers });
    } catch (cause) {
      console.warn(ioError(cause).toWire());
      return new Response(null, { status: 403 });
    }
  });
}
