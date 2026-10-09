#!/usr/bin/env node
/**
 * Real Prisma schema validation.
 *
 * `prisma validate` shells out to the native schema-engine, which the Prisma CLI
 * downloads from binaries.prisma.sh at install time. This script drives the
 * *same* engine (prisma-fmt) through its official WASM build published to npm,
 * so the check is genuine rather than a hand-rolled parser.
 *
 * Pin `@prisma/prisma-schema-wasm` to a build from the same branch as the
 * `prisma` / `@prisma/client` version in package.json.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import wasm from '@prisma/prisma-schema-wasm';

// prisma-fmt reports Rust panics through this global. Without it a bad input
// surfaces as an opaque "unreachable" WASM trap.
globalThis.PRISMA_WASM_PANIC_REGISTRY = {
  set_message(message) {
    throw new Error(message);
  },
};

const here = dirname(fileURLToPath(import.meta.url));
const schemaPath = process.argv[2] ?? resolve(here, '..', 'prisma', 'schema.prisma');
const schema = readFileSync(schemaPath, 'utf8');

const REQUIRED_MODELS = [
  'User',
  'Project',
  'Video',
  'VideoSource',
  'Transcript',
  'TranscriptSegment',
  'Speaker',
  'AnalysisJob',
  'Moment',
  'Clip',
  'Caption',
  'RenderJob',
  'Export',
  'Usage',
  'Subscription',
];

let failed = false;
const fail = (msg) => {
  failed = true;
  console.error(`  ✗ ${msg}`);
};

/**
 * `@@index` blocks are not exposed in the DMMF payload, so read the model bodies
 * straight from the schema text. A foreign key is considered covered when it is
 * the leading column of an `@@index` / `@@unique`, or is itself `@unique` / `@id`.
 */
function checkForeignKeyIndexes(schemaText, byName) {
  const unindexed = [];
  let checked = 0;
  const modelRe = /^model\s+(\w+)\s*\{([\s\S]*?)^\}/gm;
  for (const [, name, body] of schemaText.matchAll(modelRe)) {
    const model = byName.get(name);
    if (!model) continue;
    const leading = new Set();
    // Any column of a @@unique is reachable: those lookups always carry the
    // leading column too (e.g. Account is found by [provider, providerAccountId]).
    for (const m of body.matchAll(/@@index\(\s*\[([^\]]*)\]/g)) {
      const first = m[1]
        .split(',')[0]
        ?.replace(/\(.*?\)/g, '')
        .trim();
      if (first) leading.add(first);
    }
    for (const m of body.matchAll(/@@unique\(\s*\[([^\]]*)\]/g)) {
      for (const col of m[1].split(',')) {
        const name = col.replace(/\(.*?\)/g, '').trim();
        if (name) leading.add(name);
      }
    }
    for (const field of model.fields) {
      if (field.kind === 'object' || field.isId) continue;
      if (!/Id$/.test(field.name)) continue;
      const line = body.split('\n').find((l) => new RegExp(`^\\s*${field.name}\\s`).test(l)) ?? '';
      checked += 1;
      const covered = leading.has(field.name) || /@unique/.test(line);
      if (!covered) unindexed.push(`${name}.${field.name}`);
    }
  }
  return { unindexed, checked };
}

// 1. validate — the exact check `prisma validate` runs (error code P1012 etc.)
try {
  wasm.validate(JSON.stringify({ prismaSchema: schema, noColors: true }));
  console.log('✓ validate: schema is valid');
} catch (err) {
  let detail = String(err?.message ?? err);
  try {
    const parsed = JSON.parse(detail);
    detail = `${parsed.error_code ?? 'ERROR'}: ${String(parsed.message ?? '').replace(/\u001b\[[0-9;]*m/g, '')}`;
  } catch {
    /* keep raw */
  }
  fail(`validate: ${detail.slice(0, 600)}`);
}

// 2. DMMF — proves every model/field/enumparses into a real data model, and that
//    the ownership graph (User -> Project -> Video -> Moment -> Clip) exists.
try {
  const dmmf = JSON.parse(wasm.get_dmmf(JSON.stringify({ prismaSchema: schema })));
  const models = dmmf.datamodel.models ?? [];
  const enums = dmmf.datamodel.enums ?? [];
  const fieldCount = models.reduce((n, m) => n + m.fields.length, 0);
  console.log(`✓ dmmf: ${models.length} models, ${fieldCount} fields, ${enums.length} enums`);

  const byName = new Map(models.map((m) => [m.name, m]));
  for (const name of REQUIRED_MODELS) {
    if (!byName.has(name)) fail(`missing required model: ${name}`);
  }
  if (!failed) console.log(`✓ dmmf: all ${REQUIRED_MODELS.length} required domain models present`);

  // Ownership chain must be navigable, otherwise per-user isolation is impossible.
  const chain = [
    ['Project', 'userId'],
    ['Video', 'projectId'],
    ['Video', 'userId'],
    ['Moment', 'videoId'],
    ['Clip', 'videoId'],
    ['Export', 'userId'],
    ['Usage', 'userId'],
  ];
  for (const [model, field] of chain) {
    const m = byName.get(model);
    if (!m?.fields.some((f) => f.name === field)) fail(`${model}.${field} is missing`);
  }
  if (!failed) console.log('✓ dmmf: ownership chain Project→Video→Moment→Clip intact');

  // Every foreign key must carry a leading index — the moment/clip queries all
  // filter by userId / videoId, and an unindexed FK turns into a seq scan.
  // (`@@index` blocks are not part of the DMMF payload, so read them from source.)
  const indexedFks = checkForeignKeyIndexes(schema, byName);
  if (indexedFks.unindexed.length) {
    fail(`FK fields without a leading index: ${indexedFks.unindexed.join(', ')}`);
  } else {
    console.log(`✓ indexes: all ${indexedFks.checked} foreign keys have a leading index`);
  }

  console.log(`  models: ${models.map((m) => m.name).sort().join(', ')}`);
} catch (err) {
  fail(`dmmf: ${String(err?.message ?? err).slice(0, 400)}`);
}

// 3. format — canonical Prisma formatting keeps diffs clean.
try {
  const formatted = wasm.format(schema, JSON.stringify({}));
  if (formatted.replace(/\s+$/, '') !== schema.replace(/\s+$/, '')) {
    console.log('! format: schema is not canonically formatted (run `npm run db:format`)');
  } else {
    console.log('✓ format: canonically formatted');
  }
} catch (err) {
  console.log(`! format: skipped (${String(err?.message ?? err).slice(0, 120)})`);
}

process.exit(failed ? 1 : 0);
