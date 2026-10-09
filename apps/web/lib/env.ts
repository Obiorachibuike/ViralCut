/** Typed access to the small set of env vars the web app reads. */
export const env = {
  databaseUrl: process.env.DATABASE_URL,
  mediaEngineUrl: process.env.FASTAPI_URL ?? process.env.MEDIA_ENGINE_URL ?? 'http://127.0.0.1:8000',
  mediaEngineToken: process.env.MEDIA_ENGINE_TOKEN ?? '',
  callbackBaseUrl: process.env.VIRALCUT_CALLBACK_BASE_URL ?? '',
  appUrl: process.env.NEXT_PUBLIC_APP_URL ?? 'http://localhost:3000',
  redisUrl: process.env.REDIS_URL,
  queueDriver: (process.env.QUEUE_DRIVER ?? (process.env.REDIS_URL ? 'redis' : 'inline')) as 'redis' | 'inline',
} as const;

export function mediaHeaders(): Record<string, string> {
  return {
    'content-type': 'application/json',
    'x-viralcut-token': env.mediaEngineToken,
  };
}
