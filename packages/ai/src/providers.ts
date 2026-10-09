import { z } from 'zod';

/**
 * AIProvider — the abstraction ViralCut is built against.
 *
 * Nothing in the app imports a vendor SDK directly. Swapping models means
 * changing `VIRALCUT_AI_PROVIDER` (+ the matching key), not touching call sites.
 */

export interface ChatMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
}

export interface CompleteOptions {
  temperature?: number;
  maxTokens?: number;
  json?: boolean;
  signal?: AbortSignal;
}

export interface CompletionResult {
  text: string;
  model: string;
  provider: string;
  usage?: { inputTokens: number; outputTokens: number };
}

export interface AIProvider {
  readonly id: string;
  readonly model: string;
  readonly available: boolean;
  complete(messages: ChatMessage[], opts?: CompleteOptions): Promise<CompletionResult>;
}

/** Vendor-neutral error so callers never have to know which SDK blew up. */
export class AIProviderError extends Error {
  constructor(
    message: string,
    readonly provider: string,
    readonly cause?: unknown,
  ) {
    super(message);
    this.name = 'AIProviderError';
  }
}

/** Strip markdown fences and any prose around a JSON payload. */
export function extractJson<T = unknown>(raw: string, schema?: z.ZodType<T>): T {
  let text = raw.trim();
  const fence = text.match(/```(?:json)?\s*([\s\S]*?)```/i);
  if (fence) text = fence[1].trim();
  const first = text.search(/[[{]/);
  if (first > 0) text = text.slice(first);
  const lastBrace = Math.max(text.lastIndexOf('}'), text.lastIndexOf(']'));
  if (lastBrace >= 0) text = text.slice(0, lastBrace + 1);
  const parsed = JSON.parse(text) as unknown;
  return schema ? schema.parse(parsed) : (parsed as T);
}

// ---------------------------------------------------------------------------
// OpenAI-compatible (OpenAI, Azure OpenAI, OpenRouter, Groq, Together, Ollama…)
// ---------------------------------------------------------------------------

export interface OpenAICompatibleConfig {
  apiKey: string;
  model?: string;
  baseUrl?: string;
  id?: string;
}

export class OpenAICompatibleProvider implements AIProvider {
  readonly id: string;
  readonly model: string;
  readonly available = true;
  private readonly baseUrl: string;
  private readonly apiKey: string;

  constructor(config: OpenAICompatibleConfig) {
    this.id = config.id ?? 'openai-compatible';
    this.model = config.model ?? 'gpt-4o-mini';
    this.baseUrl = (config.baseUrl ?? 'https://api.openai.com/v1').replace(/\/$/, '');
    this.apiKey = config.apiKey;
  }

  async complete(messages: ChatMessage[], opts: CompleteOptions = {}): Promise<CompletionResult> {
    const res = await fetch(`${this.baseUrl}/chat/completions`, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        authorization: `Bearer ${this.apiKey}`,
      },
      body: JSON.stringify({
        model: this.model,
        messages,
        temperature: opts.temperature ?? 0.3,
        max_tokens: opts.maxTokens ?? 2000,
        ...(opts.json ? { response_format: { type: 'json_object' } } : {}),
      }),
      signal: opts.signal,
    });
    if (!res.ok) {
      throw new AIProviderError(
        `AI request failed (${res.status}): ${(await res.text()).slice(0, 300)}`,
        this.id,
      );
    }
    const data = (await res.json()) as {
      choices: { message: { content: string } }[];
      usage?: { prompt_tokens: number; completion_tokens: number };
    };
    return {
      text: data.choices?.[0]?.message?.content ?? '',
      model: this.model,
      provider: this.id,
      usage: data.usage
        ? { inputTokens: data.usage.prompt_tokens, outputTokens: data.usage.completion_tokens }
        : undefined,
    };
  }
}

// ---------------------------------------------------------------------------
// Anthropic
// ---------------------------------------------------------------------------

export class AnthropicProvider implements AIProvider {
  readonly id = 'anthropic';
  readonly model: string;
  readonly available = true;
  constructor(
    private readonly apiKey: string,
    model = 'claude-sonnet-4-5',
  ) {
    this.model = model;
  }

  async complete(messages: ChatMessage[], opts: CompleteOptions = {}): Promise<CompletionResult> {
    const system = messages.filter((m) => m.role === 'system').map((m) => m.content).join('\n\n');
    const rest = messages.filter((m) => m.role !== 'system');
    const res = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-api-key': this.apiKey,
        'anthropic-version': '2023-06-01',
      },
      body: JSON.stringify({
        model: this.model,
        max_tokens: opts.maxTokens ?? 2000,
        temperature: opts.temperature ?? 0.3,
        system,
        messages: rest,
      }),
      signal: opts.signal,
    });
    if (!res.ok) {
      throw new AIProviderError(
        `AI request failed (${res.status}): ${(await res.text()).slice(0, 300)}`,
        this.id,
      );
    }
    const data = (await res.json()) as {
      content: { type: string; text: string }[];
      usage?: { input_tokens: number; output_tokens: number };
    };
    return {
      text: data.content?.map((c) => c.text ?? '').join('') ?? '',
      model: this.model,
      provider: this.id,
      usage: data.usage
        ? { inputTokens: data.usage.input_tokens, outputTokens: data.usage.output_tokens }
        : undefined,
    };
  }
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

export interface AIProviderConfig {
  provider?: string;
  apiKey?: string;
  model?: string;
  baseUrl?: string;
}

export function createAIProvider(config: AIProviderConfig = {}): AIProvider | null {
  const provider = (config.provider ?? process.env.VIRALCUT_AI_PROVIDER ?? 'openai').toLowerCase();
  const apiKey = config.apiKey ?? process.env.AI_API_KEY ?? '';
  const model = config.model ?? process.env.VIRALCUT_AI_MODEL;

  if (!apiKey) return null;

  switch (provider) {
    case 'anthropic':
      return new AnthropicProvider(apiKey, model);
    case 'openai':
      return new OpenAICompatibleProvider({ apiKey, model: model ?? 'gpt-4o-mini' });
    case 'openrouter':
      return new OpenAICompatibleProvider({
        apiKey,
        model: model ?? 'openai/gpt-4o-mini',
        baseUrl: 'https://openrouter.ai/api/v1',
        id: 'openrouter',
      });
    case 'groq':
      return new OpenAICompatibleProvider({
        apiKey,
        model: model ?? 'llama-3.3-70b-versatile',
        baseUrl: 'https://api.groq.com/openai/v1',
        id: 'groq',
      });
    case 'ollama':
      return new OpenAICompatibleProvider({
        apiKey,
        model: model ?? 'llama3.1',
        baseUrl: process.env.OLLAMA_BASE_URL ?? 'http://localhost:11434/v1',
        id: 'ollama',
      });
    default:
      // Any OpenAI-compatible endpoint: set VIRALCUT_AI_BASE_URL.
      return new OpenAICompatibleProvider({
        apiKey,
        model: model ?? 'gpt-4o-mini',
        baseUrl: config.baseUrl ?? process.env.VIRALCUT_AI_BASE_URL,
        id: provider,
      });
  }
}

/**
 * True when a real LLM is configured. ViralCut never fakes an AI analysis:
 * when no key is present the caller must use the deterministic analyser and
 * tell the user the LLM upgrade is available.
 */
export function hasLLMConfigured(): boolean {
  return Boolean(process.env.AI_API_KEY);
}
