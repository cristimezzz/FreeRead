import { expect, test } from 'vitest';
import { BUDGETS } from './budgets';
test('exports the frozen performance gates', () => {
  expect(BUDGETS.COLD_START_MS).toBe(2500);
  expect(BUDGETS.ANCHOR_IOU_MIN).toBe(0.98);
  expect(BUDGETS.BLOCK_F1_MIN).toBe(0.9);
});
