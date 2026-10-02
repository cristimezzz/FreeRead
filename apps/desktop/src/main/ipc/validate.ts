import Ajv2020 from 'ajv/dist/2020';
import addFormats from 'ajv-formats';
import { z } from 'zod';
import { CONTRACT_SCHEMAS } from './contract-data.generated';

const ajv = new Ajv2020({ strict: false, allErrors: true });
addFormats(ajv);
for (const schema of CONTRACT_SCHEMAS) ajv.addSchema(schema);
const manifest = CONTRACT_SCHEMAS.find((schema) => schema['$id'] === 'https://freeread.dev/schemas/ipc-channels.json');
if (!manifest) throw new Error('Missing generated IPC manifest');
const definitions: unknown = manifest['$defs'];

export function createValidator(name: string) {
  const schema: unknown = typeof definitions === 'object' && definitions !== null
    ? Reflect.get(definitions, name) : undefined;
  const validate = ajv.compile({ $ref: `https://freeread.dev/schemas/ipc-channels.json#/$defs/${name}` });
  const properties: unknown = typeof schema === 'object' && schema !== null
    ? Reflect.get(schema, 'properties') : undefined;
  const base = typeof properties === 'object' && properties !== null
    ? z.object(Object.fromEntries(Object.keys(properties).map((key) => [key, z.unknown().optional()]))).strict()
    : z.unknown();
  // AJV enforces nested strictness, oneOf exclusivity and conditional schema constraints.
  return base.superRefine((value, context) => {
    if (!validate(value)) context.addIssue({ code: 'custom', message: 'FR-IPC-002' });
  });
}
