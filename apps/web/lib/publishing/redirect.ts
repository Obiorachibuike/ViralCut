import { env } from '../env';

/**
 * The OAuth redirect URI must be byte-identical at authorize and callback time,
 * so it is derived in exactly one place. Behind a proxy `request.url` can carry
 * an internal origin, so the configured app URL wins when present.
 */
export function redirectUriFor(request: Request, platform: string): string {
  const base = (env.appUrl || new URL(request.url).origin).replace(/\/$/, '');
  return `${base}/api/social/callback/${platform.toLowerCase()}`;
}

export function appBase(request: Request): string {
  return (env.appUrl || new URL(request.url).origin).replace(/\/$/, '');
}
