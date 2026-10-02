import { writeFileSync } from 'node:fs';

// Original, generated text-only PDF; no third-party content or external assets.
export function writePdf(path: string, pageCount = 3) {
  const objects: string[] = ['', '<< /Type /Catalog /Pages 2 0 R >>', ''];
  const kids: number[] = [];
  for (let page = 1; page <= pageCount; page++) {
    const pageId = objects.length, streamId = pageId + 1; kids.push(pageId);
    objects.push(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 ${3 + pageCount * 2} 0 R >> >> /Contents ${streamId} 0 R >>`);
    const content = `BT /F1 14 Tf 50 720 Td (Page ${page} first sentence. Next sentence.) Tj 0 -50 Td (Attention original research.) Tj ET`;
    objects.push(`<< /Length ${Buffer.byteLength(content)} >>\nstream\n${content}\nendstream`);
  }
  objects[2] = `<< /Type /Pages /Kids [${kids.map((id) => `${id} 0 R`).join(' ')}] /Count ${pageCount} >>`;
  objects.push('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>');
  let pdf = '%PDF-1.7\n', offsets = '0000000000 65535 f \n';
  objects.slice(1).forEach((object, i) => { offsets += `${String(Buffer.byteLength(pdf)).padStart(10, '0')} 00000 n \n`; pdf += `${i + 1} 0 obj\n${object}\nendobj\n`; });
  const xref = Buffer.byteLength(pdf);
  pdf += `xref\n0 ${objects.length}\n${offsets}trailer\n<< /Size ${objects.length} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  writeFileSync(path, pdf);
}
