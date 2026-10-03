// SPDX-License-Identifier: AGPL-3.0-only
import { expect, test } from 'vitest';
import { createValidator } from './validate';

test('IPC schema rejects nested, extra and out-of-range input before and after a valid request', () => {
  const validator = createValidator('LibraryListRequest');
  expect(validator.safeParse({ offset: 0, limit: 10, tags: [42] }).success).toBe(false);
  expect(validator.safeParse({ offset: 0, limit: 10, tags: ['NLP'] }).success).toBe(true);
  expect(validator.safeParse({ offset: 0, limit: 10, unexpected: true }).success).toBe(false);
  expect(validator.safeParse({ offset: 0, limit: 0 }).success).toBe(false);
});
