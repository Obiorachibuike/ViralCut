import { env, mediaHeaders } from './env';

/** Typed client for the FastAPI media engine. Server-side only. */
export interface MediaResolveResult {
  kind: string;
  provider: string;
  permitted: boolean;
  externalId: string | null;
  title: string | null;
  reason: string | null;
  isPrivate: boolean;
  requiresLogin: boolean;
  drmProtected: boolean;
  isLive: boolean;
  providers: { kind: string; name: string; enabled: boolean; note: string }[];
}

export interface MediaRunState {
  runId: string;
  state: string;
  progress: number;
  events: { stage: string; progress: number; message: string; at: number }[];
  result: Record<string, unknown> | null;
  error: string | null;
  errorCode: string | null;
}

async function call<T>(path: string, init?: RequestInit, timeoutMs = 30_000): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${env.mediaEngineUrl}${path}`, {
      ...init,
      headers: { ...mediaHeaders(), ...(init?.headers ?? {}) },
      signal: controller.signal,
    });
    const body = (await res.json().catch(() => ({}))) as Record<string, any>;
    if (!res.ok) {
      const message = (body as any)?.error?.message ?? `Media engine error (HTTP ${res.status})`;
      throw new MediaEngineError(message, (body as any)?.error?.code, res.status);
    }
    return body as T;
  } finally {
    clearTimeout(timer);
  }
}

export class MediaEngineError extends Error {
  constructor(
    message: string,
    readonly code?: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = 'MediaEngineError';
  }
}

export const media = {
  health: () => call<Record<string, unknown>>('/v1/health'),

  resolveUrl: (url: string) =>
    call<MediaResolveResult>('/v1/ingest/resolve-url', {
      method: 'POST',
      body: JSON.stringify({ url }),
    }),

  download: (url: string, runId: string) =>
    call<{ storageKey: string; sizeBytes: number; kind: string; provider: string }>(
      '/v1/ingest/download',
      { method: 'POST', body: JSON.stringify({ url, runId }) },
      10 * 60_000,
    ),

  process: (body: Record<string, unknown>) =>
    call<{ runId: string; state: string; queued: boolean }>('/v1/process', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  run: (runId: string) => call<MediaRunState>(`/v1/runs/${encodeURIComponent(runId)}`),

  render: (body: Record<string, unknown>) =>
    call<Record<string, unknown>>('/v1/clips/render', {
      method: 'POST',
      body: JSON.stringify(body),
    }, 15 * 60_000),

  captions: (body: Record<string, unknown>) =>
    call<Record<string, unknown>>('/v1/captions/generate', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  reframePlan: (body: Record<string, unknown>) =>
    call<Record<string, unknown>>('/v1/reframe/plan', { method: 'POST', body: JSON.stringify(body) }),

  /** Which text-to-video backends the engine can actually use. */
  t2vProviders: () =>
    call<{
      active: string | null;
      activeConfigured: boolean;
      maxSeconds: number;
      providers: { name: string; label: string; configured: boolean; reason?: string }[];
    }>('/v1/generate/providers'),

  generateTextToVideo: (body: Record<string, unknown>) =>
    call<{ runId: string; state: string; queued: boolean }>('/v1/generate/text-to-video', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  /** Short-lived URL for a stored object; how the publisher fetches a clip. */
  storageUrl: (key: string, expiresIn = 900) =>
    call<{ key: string; url: string; expiresIn: number; sizeBytes: number }>(
      `/v1/storage/url?key=${encodeURIComponent(key)}&expires_in=${expiresIn}`,
    ),
};
