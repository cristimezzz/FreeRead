#!/usr/bin/env node
/**
 * check-specs.mjs — 规范集自检（无第三方依赖）
 *
 * 用法：node specs/tools/check-specs.mjs
 * 退出码：0 = 全部通过；1 = 存在失败项
 *
 * 检查项：
 *   C1  README §2 索引中列出的规范文件都存在
 *   C2  每个规范文件都含「变更记录」小节
 *   C3  schemas/*.json 均为合法 JSON，且含 $schema / $id
 *   C4  schema 内部 $ref（#/$defs/...）可解析
 *   C5  schema 跨文件 $ref（https://freeread.dev/schemas/<f>.json）指向存在的文件
 *   C6  ipc-channels.json 结构合法：通道名唯一、命名匹配 fr:<domain>:<action>、kind ∈ {invoke,event}
 *   C7  ipc-channels.json 中的通道与 06-ipc-contract.md 中出现的通道一致（双向）
 *   C8  所有规范中出现的错误码 FR-XXX-NNN 均在 11-error-handling.md 中定义
 *   C9  禁止域名（黑名单）只允许出现在 09-fetch-compliance.md 中
 *   C10 规范文件命名与 README 索引一致（NN-name.md）
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SPECS = path.resolve(__dirname, '..');
const ROOT = path.resolve(SPECS, '..');

const results = [];
const fail = (id, msg) => results.push({ id, ok: false, msg });
const pass = (id, msg) => results.push({ id, ok: true, msg });

const read = (p) => fs.readFileSync(p, 'utf8');
const exists = (p) => fs.existsSync(p);

// ---------------------------------------------------------------- C1
const readme = read(path.join(SPECS, 'README.md'));
const indexed = [...readme.matchAll(/\|\s*`(\d{2}-[a-z0-9-]+\.md)`\s*\|/g)].map((m) => m[1]);
const extraIndexed = [...readme.matchAll(/\|\s*`(schemas\/[^`]+)`\s*\|/g)].map((m) => m[1]);
if (indexed.length === 0) fail('C1', 'README §2 未解析到任何规范文件条目');
else {
  const missing = indexed.filter((f) => !exists(path.join(SPECS, f)));
  missing.length ? fail('C1', `索引列出但缺失: ${missing.join(', ')}`) : pass('C1', `${indexed.length} 个规范文件均存在`);
}
void extraIndexed;

// ---------------------------------------------------------------- C2
const specFiles = fs.readdirSync(SPECS).filter((f) => /^\d{2}-.*\.md$/.test(f));
const noChangelog = specFiles.filter((f) => !/变更记录/.test(read(path.join(SPECS, f))));
noChangelog.length ? fail('C2', `缺少「变更记录」: ${noChangelog.join(', ')}`) : pass('C2', `${specFiles.length} 个文件均有变更记录`);

// ---------------------------------------------------------------- C3-C5
const schemaDir = path.join(SPECS, 'schemas');
const schemaFiles = exists(schemaDir) ? fs.readdirSync(schemaDir).filter((f) => f.endsWith('.json')) : [];
const schemas = {};
for (const f of schemaFiles) {
  try {
    const j = JSON.parse(read(path.join(schemaDir, f)));
    schemas[f] = j;
    if (!j.$schema) fail('C3', `${f} 缺少 $schema`);
    if (!j.$id) fail('C3', `${f} 缺少 $id`);
  } catch (e) {
    fail('C3', `${f} 不是合法 JSON: ${e.message}`);
  }
}
if (Object.keys(schemas).length) pass('C3', `${Object.keys(schemas).length} 个 schema 解析成功`);

function collectRefs(node, out = []) {
  if (node && typeof node === 'object') {
    if (typeof node.$ref === 'string') out.push(node.$ref);
    for (const v of Object.values(node)) collectRefs(v, out);
  }
  return out;
}
let localRefFail = 0, remoteRefFail = 0;
for (const [f, j] of Object.entries(schemas)) {
  for (const ref of collectRefs(j)) {
    if (ref.startsWith('#/')) {
      const parts = ref.slice(2).split('/');
      let cur = j;
      for (const p of parts) cur = cur?.[p];
      if (cur === undefined) { fail('C4', `${f}: 无法解析 ${ref}`); localRefFail++; }
    } else if (ref.startsWith('https://freeread.dev/schemas/')) {
      const target = ref.split('#')[0].split('/').pop();
      if (!schemas[target]) { fail('C5', `${f}: 跨文件引用目标不存在 ${ref}`); remoteRefFail++; }
    }
  }
}
if (!localRefFail) pass('C4', '所有本地 $ref 可解析');
if (!remoteRefFail) pass('C5', '所有跨文件 $ref 指向存在的 schema');

// ---------------------------------------------------------------- C6-C7
const ipcFile = path.join(schemaDir, 'ipc-channels.json');
if (!exists(ipcFile)) fail('C6', 'schemas/ipc-channels.json 不存在');
else {
  const ipc = schemas['ipc-channels.json'] ?? JSON.parse(read(ipcFile));
  const chans = Array.isArray(ipc.channels) ? ipc.channels : [];
  const events = Array.isArray(ipc.events) ? ipc.events : [];
  const names = [...chans, ...events].map((c) => c.name);
  const dup = names.filter((n, i) => names.indexOf(n) !== i);
  const bad = names.filter((n) => !/^fr:[a-z]+:[a-zA-Z][a-zA-Z0-9]*$/.test(String(n)));
  const badKind = chans.filter((c) => c.kind !== 'invoke');
  if (!names.length) fail('C6', '未解析到任何通道');
  else if (dup.length) fail('C6', `通道名重复: ${[...new Set(dup)].join(', ')}`);
  else if (bad.length) fail('C6', `通道命名不合规: ${bad.join(', ')}`);
  else if (badKind.length) fail('C6', `invoke 通道 kind 必须为 "invoke": ${badKind.map((c) => c.name).join(', ')}`);
  else pass('C6', `${chans.length} 个 invoke 通道 + ${events.length} 个事件，命名与唯一性通过`);

  const contract = exists(path.join(SPECS, '06-ipc-contract.md')) ? read(path.join(SPECS, '06-ipc-contract.md')) : '';
  if (!contract) fail('C7', '06-ipc-contract.md 不存在，无法交叉校验');
  else {
    const inMd = new Set([...contract.matchAll(/`(fr:[a-z]+:[a-zA-Z0-9]+)`/g)].map((m) => m[1]));
    const missingInMd = names.filter((n) => !inMd.has(n));
    const missingInJson = [...inMd].filter((n) => !names.includes(n));
    if (missingInMd.length) fail('C7', `JSON 有但契约文档缺: ${missingInMd.join(', ')}`);
    else if (missingInJson.length) fail('C7', `契约文档有但 JSON 缺: ${missingInJson.join(', ')}`);
    else pass('C7', `${names.length} 个通道在 JSON 与契约文档中一致`);
  }
}

// ---------------------------------------------------------------- C8
const ERR_RE = /FR-[A-Z]{2,8}-\d{3}/g;
const errDoc = exists(path.join(SPECS, '11-error-handling.md')) ? read(path.join(SPECS, '11-error-handling.md')) : '';
const defined = new Set([...errDoc.matchAll(ERR_RE)].map((m) => m[0]));
const used = new Map();
for (const f of [...specFiles.map((x) => path.join(SPECS, x)), ...fs.readdirSync(schemaDir).map((x) => path.join(schemaDir, x)), path.join(ROOT, 'AGENTS.md')]) {
  if (!exists(f) || !/\.(md|json)$/.test(f)) continue;
  if (path.basename(f) === '11-error-handling.md') continue;
  for (const m of read(f).matchAll(ERR_RE)) {
    if (!used.has(m[0])) used.set(m[0], path.basename(f));
  }
}
if (!defined.size) fail('C8', '11-error-handling.md 未定义任何错误码');
else {
  const undef = [...used.keys()].filter((c) => !defined.has(c));
  undef.length
    ? fail('C8', `${undef.length} 个错误码被引用但未定义: ${undef.slice(0, 12).join(', ')}${undef.length > 12 ? ' …' : ''}`)
    : pass('C8', `${defined.size} 个错误码已定义，${used.size} 个被引用的错误码全部可追溯`);
}

// ---------------------------------------------------------------- C9
// 禁止域名只能出现在合规文档，或出现在"门禁/黑名单"语境的说明行（如 forbid-domains 脚本说明）
const BLACK = ['sci-hub', 'libgen', 'z-lib', 'annas-archive'];
const ALLOW_CTX = /(forbid|禁用域名|黑名单|blacklist|门禁|grep)/i;
const offenders = [];
for (const f of specFiles.map((x) => path.join(SPECS, x))) {
  const base = path.basename(f);
  if (base === '09-fetch-compliance.md') continue;
  const lines = read(f).split('\n');
  lines.forEach((line, i) => {
    const low = line.toLowerCase();
    if (!BLACK.some((b) => low.includes(b))) return;
    if (ALLOW_CTX.test(line)) return;           // 门禁说明行，允许
    offenders.push(`${base}:${i + 1}`);
  });
}
offenders.length ? fail('C9', `禁止域名出现在非合规文档（非门禁语境）: ${offenders.join(', ')}`) : pass('C9', '禁止域名仅出现在 09 或门禁说明中');

// ---------------------------------------------------------------- C10
const badName = specFiles.filter((f) => !indexed.includes(f));
badName.length ? fail('C10', `未被 README 索引的规范文件: ${badName.join(', ')}`) : pass('C10', '文件命名与索引一致');

// ---------------------------------------------------------------- C11
// 任何规范文档中出现的 `fr:...` 通道名都必须存在于 schemas/ipc-channels.json（唯一真源）
{
  const ipcFile2 = path.join(schemaDir, 'ipc-channels.json');
  if (!exists(ipcFile2)) fail('C11', 'ipc-channels.json 不存在，无法校验通道引用');
  else {
    const ipc2 = JSON.parse(read(ipcFile2));
    const canonical = new Set([...(ipc2.channels || []), ...(ipc2.events || [])].map((c) => c.name));
    const offenders2 = [];
    for (const f of specFiles.map((x) => path.join(SPECS, x))) {
      const base = path.basename(f);
      read(f).split('\n').forEach((line, i) => {
        for (const m of line.matchAll(/`(fr:[A-Za-z0-9:_*-]+)`/g)) {
          const name = m[1];
          if (name.includes('*')) continue;                 // fr:* 通配写法允许
          if (!canonical.has(name)) offenders2.push(`${base}:${i + 1} \`${name}\``);
        }
      });
    }
    const uniq2 = [...new Set(offenders2)];
    uniq2.length
      ? fail('C11', `${uniq2.length} 处引用了契约外的通道名:\n        ${uniq2.slice(0, 15).join('\n        ')}${uniq2.length > 15 ? '\n        …' : ''}`)
      : pass('C11', '所有规范引用的 fr: 通道名均在契约清单内');
  }
}

// ---------------------------------------------------------------- report
const width = 6;
console.log('\nFreeRead 规范自检\n' + '='.repeat(60));
for (const r of results) {
  console.log(`${r.ok ? 'PASS' : 'FAIL'}  ${r.id.padEnd(width)} ${r.msg}`);
}
const failed = results.filter((r) => !r.ok);
console.log('='.repeat(60));
console.log(`总计 ${results.length} 项，失败 ${failed.length} 项`);
if (failed.length) {
  console.log('\n失败明细见上。请修正后重跑：node specs/tools/check-specs.mjs');
  process.exit(1);
}
console.log('规范集自检通过 ✅');
