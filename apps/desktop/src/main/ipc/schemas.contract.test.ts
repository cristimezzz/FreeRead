import { describe, expect, test } from 'vitest';
import { CHANNEL_REGISTRY } from './registry.generated';
import { IPC_SCHEMAS } from './schemas.generated';

describe('generated IPC contracts', () => {
  test('covers every frozen request and response, and rejects unknown fields', () => {
    expect(Object.keys(IPC_SCHEMAS).sort()).toEqual(CHANNEL_REGISTRY.map((c) => c.name).sort());
    for (const schemas of Object.values(IPC_SCHEMAS)) {
      expect(schemas.request.safeParse({ __unknown: true }).success).toBe(false);
      expect(schemas.response.safeParse({ __unknown: true }).success).toBe(false);
      expect(schemas.request.safeParse(null).success).toBe(false);
    }
  });
  test('strict empty request succeeds; config patch rejects nested unknown fields', () => {
    expect(IPC_SCHEMAS['fr:app:getCapabilities'].request.safeParse({}).success).toBe(true);
    expect(IPC_SCHEMAS['fr:app:setConfig'].request.safeParse({ patch: { __unknown: true } }).success).toBe(false);
    expect(IPC_SCHEMAS['fr:app:setConfig'].request.safeParse({ patch: { reader: { __unknown: true } } }).success).toBe(false);
    expect(IPC_SCHEMAS['fr:app:setConfig'].request.safeParse({ patch: { locale: 'en' } }).success).toBe(true);
  });
});
