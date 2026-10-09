#!/usr/bin/env node
/** Canonicalise prisma/schema.prisma with the real prisma-fmt WASM engine. */
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import wasm from '@prisma/prisma-schema-wasm';

globalThis.PRISMA_WASM_PANIC_REGISTRY = { set_message(m) { throw new Error(m); } };
const here = dirname(fileURLToPath(import.meta.url));
const p = process.argv[2] ?? resolve(here, '..', 'prisma', 'schema.prisma');
const out = wasm.format(readFileSync(p, 'utf8'), JSON.stringify({}));
writeFileSync(p, out);
console.log(`formatted ${p}`);
