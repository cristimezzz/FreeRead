import { test } from 'node:test';
import assert from 'node:assert/strict';
import { isAllowed } from './license-policy.mjs';

test('allows AGPL and rejects every forbidden or unknown license', () => {
  for (const license of ['AGPL-3.0', 'GPL-3.0-only', 'MIT', '(MIT OR Apache-2.0)', 'MIT AND BSD-3-Clause']) assert.ok(isAllowed(license), license);
  for (const license of ['SSPL-1.0', 'BUSL-1.1', 'Elastic-2.0', 'GPL-2.0-only', 'UNLICENSED', 'Proprietary', 'CC-BY-NC-4.0', 'unknown', 'MIT OR SSPL-1.0', undefined]) assert.equal(isAllowed(license), false, license);
});
