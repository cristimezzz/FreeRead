import { expect, test } from 'vitest';
import { AppError, toAppError } from './error';

test('wire roundtrip strips stack and cause and freezes details', () => {
  const original = new AppError('FR-IPC-001', { category: 'ipc', severity: 'fatal',
    retryable: false, i18nKey: 'errors.FR-IPC-001', message: 'Unknown channel',
    cause: new Error('private cause'), details: { count: 1 } });
  const wire = original.toWire();
  expect(Object.isFrozen(original.details)).toBe(true);
  expect(wire).not.toHaveProperty('stack');
  expect(wire).not.toHaveProperty('cause');
  expect(AppError.fromWire(wire).toWire()).toEqual(wire);
  expect(toAppError(original)).toBe(original);
});
test('unknown throws receive a registered fallback code without leaking payloads', () => {
  for (const cause of [new Error('private path'), 'secret', undefined]) {
    const error = toAppError(cause);
    expect(error.code).toBe('FR-SYS-003');
    expect(error.message).toBe('FR-SYS-003');
    expect(error.toWire().details).toEqual({});
  }
  expect(toAppError(null, 'FR-SYS-001').code).toBe('FR-SYS-001');
});
