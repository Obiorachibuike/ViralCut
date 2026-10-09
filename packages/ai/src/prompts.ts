import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export interface PromptSpec {
  id: string;
  version: string;
  description: string;
  temperature: number;
  maxOutputTokens: number;
  responseFormat: 'json' | 'text';
  system: string;
  userTemplate: string;
  variables: string[];
}

const here = typeof __dirname !== 'undefined' ? __dirname : dirname(fileURLToPath(import.meta.url));
/** packages/ai/prompts — overridable for packaged deployments. */
const PROMPT_DIR = process.env.VIRALCUT_PROMPT_DIR
  ? resolve(process.env.VIRALCUT_PROMPT_DIR)
  : resolve(here, '..', 'prompts');

export const DEFAULT_PROMPT_VERSION = process.env.VIRALCUT_PROMPT_VERSION ?? 'v1';

const cache = new Map<string, PromptSpec>();

export function promptVersions(): string[] {
  if (!existsSync(PROMPT_DIR)) return [];
  return readdirSync(PROMPT_DIR, { withFileTypes: true })
    .filter((d) => d.isDirectory())
    .map((d) => d.name)
    .sort();
}

export function getPrompt(id: string, version: string = DEFAULT_PROMPT_VERSION): PromptSpec {
  const key = `${version}/${id}`;
  const cached = cache.get(key);
  if (cached) return cached;
  const file = join(PROMPT_DIR, version, `${id}.json`);
  if (!existsSync(file)) {
    throw new Error(`Prompt "${id}" (version ${version}) not found at ${file}`);
  }
  const spec = JSON.parse(readFileSync(file, 'utf8')) as PromptSpec;
  cache.set(key, spec);
  return spec;
}

/** Fill `{{var}}` placeholders. Unknown placeholders are left intact so bugs are visible. */
export function renderTemplate(template: string, vars: Record<string, unknown>): string {
  return template.replace(/\{\{\s*([a-zA-Z0-9_]+)\s*\}\}/g, (match, name: string) => {
    if (!(name in vars)) return match;
    const v = vars[name];
    return typeof v === 'string' ? v : JSON.stringify(v);
  });
}

export function renderPrompt(id: string, vars: Record<string, unknown>, version?: string) {
  const spec = getPrompt(id, version);
  const missing = spec.variables.filter((v) => !(v in vars));
  if (missing.length) {
    throw new Error(`Prompt "${id}" is missing variables: ${missing.join(', ')}`);
  }
  return {
    spec,
    system: renderTemplate(spec.system, vars),
    user: renderTemplate(spec.userTemplate, vars),
  };
}

/** Stable identifier recorded on every analysis so results are reproducible. */
export function promptFingerprint(id: string, version: string = DEFAULT_PROMPT_VERSION): string {
  return `${id}@${version}`;
}
