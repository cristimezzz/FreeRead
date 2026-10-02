import { test } from 'node:test';
import assert from 'node:assert/strict';
import { forbiddenPattern } from './forbid-domains.mjs';
test('forbidden domain gate recognizes separators and case', () => {
  for (const value of ['SCI-HUB.se', 'sci_hub', 'scihub.example', 'libgen.is', 'paywall-bypass']) assert.ok(forbiddenPattern.test(value));
  assert.equal(forbiddenPattern.test('https://arxiv.org/'), false);
});
