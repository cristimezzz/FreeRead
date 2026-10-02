import { ipcMain, dialog, BrowserWindow } from 'electron';
import type { IpcMainInvokeEvent } from 'electron';
import { basename } from 'node:path';
import { atomicWrite, fail, ioError } from '../infra/files';
import { CHANNEL_REGISTRY } from './registry.generated';
import { IPC_SCHEMAS } from './schemas.generated';
import type { FrChannelName, IpcPayloads } from '@freeread/core';
import type { LibraryService } from '../services/library-service';
import type { NoteService } from '../services/note-service';
import type { ReaderService } from '../services/reader-service';

export function trusted(event: IpcMainInvokeEvent) {
  if (event.senderFrame !== event.sender.mainFrame || !BrowserWindow.fromWebContents(event.sender)) throw fail('FR-IPC-002');
}
type Context = { library: LibraryService; notes: NoteService; reader: ReaderService; approvedPaths: Set<string>; importAbort: AbortController };
export function registerHandlers(library: LibraryService, notes: NoteService, reader: ReaderService) {
  const approvedPaths = new Set<string>();
  const ctx: Context = { library, notes, reader, approvedPaths, importAbort: new AbortController() };
  ipcMain.handle('fr-local:pickPdf', async (event) => {
    trusted(event);
    const choice = await dialog.showOpenDialog({ properties: ['openFile', 'multiSelections'],
      filters: [{ name: 'PDF', extensions: ['pdf'] }] });
    choice.filePaths.forEach((path) => approvedPaths.add(path));
    return choice.filePaths;
  });
  ipcMain.handle('fr-local:cancelImport', (event) => { trusted(event); ctx.importAbort.abort(); });
  for (const channel of CHANNEL_REGISTRY) ipcMain.handle(channel.name, async (event, value: unknown) => {
    try {
      trusted(event);
      const schema = IPC_SCHEMAS[channel.name];
      if (!schema.request.safeParse(value).success) throw fail('FR-IPC-002');
      const data = await dispatch(ctx, channel.name, value);
      if (!schema.response.safeParse(data).success) throw fail('FR-IPC-002');
      return { ok: true, data };
    } catch (cause) { return { ok: false, error: ioError(cause).toWire() }; }
  });
}
async function dispatch(ctx: Context, channel: FrChannelName, value: unknown): Promise<unknown> {
 const { library, notes, approvedPaths } = ctx;
    const read = (key: FrChannelName): unknown => IPC_SCHEMAS[key].request.parse(value);
    switch (channel) {
      case 'fr:library:import': {
        const req = read(channel) as IpcPayloads['LibraryImportRequest'];
        if (req.source.kind !== 'file' || !approvedPaths.delete(req.source.path)) throw fail('FR-IPC-002');
        ctx.importAbort = new AbortController();
        return library.import(req, ctx.importAbort.signal, () => undefined);
      }
      case 'fr:library:list': return library.list(read(channel) as IpcPayloads['LibraryListRequest']);
      case 'fr:library:get': return getItem(library, read(channel) as IpcPayloads['LibraryGetRequest']);
      case 'fr:library:setTags': return library.tags(read(channel) as IpcPayloads['LibrarySetTagsRequest']);
      case 'fr:library:updateMeta': {
        const req = read(channel) as IpcPayloads['LibraryUpdateMetaRequest']; return library.update(req.docId, req.patch);
      }
      case 'fr:library:remove': return library.remove(read(channel) as IpcPayloads['LibraryRemoveRequest']);
      case 'fr:library:reindex': library.init(); await notes.init(); return { documents: library.documents.size,
        annotations: notes.annotations.size, elapsedMs: 0, drift: [], warnings: library.warnings };
      case 'fr:library:listTags': return listTags(library);
      default: return dispatchNotes(ctx, channel, value);
    }
  }
function getItem(library: LibraryService, req: IpcPayloads['LibraryGetRequest']) {
    const item = req.docId ? library.get(req.docId) : [...library.documents.values()].find((d) => d.meta.citekey === req.citekey);
    if (!item) throw fail('FR-LIB-005');
    return { item: library.item(item) };
  }
function listTags(library: LibraryService) {
    const counts = new Map<string, number>();
    for (const d of library.documents.values()) for (const tag of d.meta.tags) counts.set(tag, (counts.get(tag) ?? 0) + 1);
    return { tags: [...counts].map(([tag, count]) => ({ tag, count })) };
  }
async function exportNotes(library: LibraryService, notes: NoteService, req: IpcPayloads['NotesExportMarkdownRequest']) {
    const markdown = await notes.markdown(req.docId, req.includeAnnotations);
    let fileName: string | null = null;
    if (req.saveTo === 'dialog') {
      const choice = await dialog.showSaveDialog({ defaultPath: `${library.get(req.docId).meta.citekey}.md` });
      if (choice.filePath) { atomicWrite(choice.filePath, markdown); fileName = basename(choice.filePath); }
    }
    return { docId: req.docId, markdown, bytes: Buffer.byteLength(markdown), saved: !!fileName, fileName };
  }


async function dispatchNotes(ctx: Context, channel: FrChannelName, value: unknown): Promise<unknown> {
const { library, notes, reader } = ctx;
const read = (key: FrChannelName): unknown => IPC_SCHEMAS[key].request.parse(value);
switch(channel) {
      case 'fr:app:getVersion': return { app: '0.0.0', electron: process.versions['electron'], node: process.versions.node,
        chromium: process.versions['chrome'], platform: process.platform, arch: process.arch };
      case 'fr:app:doctor': return doctor(ctx);
      case 'fr:doc:open': return reader.open(read(channel) as IpcPayloads['DocOpenRequest']);
      case 'fr:doc:close': return reader.close(read(channel) as IpcPayloads['DocCloseRequest']);
      case 'fr:doc:getAnchorModel': return reader.model(read(channel) as IpcPayloads['DocGetAnchorModelRequest']);
      case 'fr:notes:list': return notes.list(read(channel) as IpcPayloads['NotesListRequest']);
      case 'fr:notes:delete': return notes.delete(read(channel) as IpcPayloads['NotesDeleteRequest']);
      case 'fr:notes:upsert': {
        const req = read(channel) as IpcPayloads['NotesUpsertRequest']; reader.assertSession(req.sessionId, req.docId);
        return notes.upsert(req.docId, req.annotation);
      }
      case 'fr:notes:updateProgress': {
        const req = read(channel) as IpcPayloads['NotesUpdateProgressRequest']; reader.assertSession(req.sessionId, req.docId);
        return notes.saveProgress(req);
      }
      case 'fr:notes:importMarkdown': return notes.importMarkdown(read(channel) as IpcPayloads['NotesImportMarkdownRequest']);
      case 'fr:notes:exportMarkdown': return exportNotes(library, notes, read(channel) as IpcPayloads['NotesExportMarkdownRequest']);
default: throw fail('FR-IPC-001');
}
}
function doctor(ctx: Context): IpcPayloads['AppDoctorResponse'] {
  const codes = [...new Set(ctx.library.warnings)];
  return { overall: codes.length ? 'repaired' : 'ok', indexRebuilt: ctx.library.index.recovered,
    startedAt: Date.now(), finishedAt: Date.now(), checks: codes.map((code) => ({ id: 'index.drift', status: 'warn',
      code, message: code, citekey: null })) };
}
