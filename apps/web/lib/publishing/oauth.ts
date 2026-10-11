/**
 * OAuth configuration per platform.
 *
 * Kept in one place so the connect/callback routes stay generic and a new
 * network is a data change rather than new control flow. Scopes are the minimum
 * needed to upload video and identify the account — nothing broader.
 */
import { randomBytes } from 'node:crypto';

import type { SocialPlatformId } from './types';
import { PublishError } from './types';

export interface OAuthConfig {
  authorizeUrl: string;
  tokenUrl: string;
  clientId?: string;
  clientSecret?: string;
  scopes: string[];
  /** Google-style consent screen prompt. */
  extraAuthorizeParams?: Record<string, string>;
  /** X requires PKCE. */
  pkce?: boolean;
  /** Send credentials as a Basic auth header instead of in the body. */
  basicAuth?: boolean;
}

const FB_VERSION = process.env.FACEBOOK_API_VERSION ?? 'v21.0';

export const OAUTH: Record<SocialPlatformId, OAuthConfig> = {
  YOUTUBE: {
    authorizeUrl: 'https://accounts.google.com/o/oauth2/v2/auth',
    tokenUrl: 'https://oauth2.googleapis.com/token',
    clientId: process.env.YOUTUBE_CLIENT_ID ?? process.env.GOOGLE_CLIENT_ID,
    clientSecret: process.env.YOUTUBE_CLIENT_SECRET ?? process.env.GOOGLE_CLIENT_SECRET,
    scopes: [
      'openid',
      'email',
      'profile',
      'https://www.googleapis.com/auth/youtube.upload',
      'https://www.googleapis.com/auth/youtube.readonly',
    ],
    extraAuthorizeParams: { access_type: 'offline', prompt: 'consent', include_granted_scopes: 'true' },
  },
  TIKTOK: {
    authorizeUrl: 'https://www.tiktok.com/v2/auth/authorize/',
    tokenUrl: 'https://open.tiktokapis.com/v2/oauth/token/',
    clientId: process.env.TIKTOK_CLIENT_KEY,
    clientSecret: process.env.TIKTOK_CLIENT_SECRET,
    scopes: ['user.info.basic', 'video.publish'],
  },
  FACEBOOK: {
    authorizeUrl: `https://www.facebook.com/${FB_VERSION}/dialog/oauth`,
    tokenUrl: `https://graph.facebook.com/${FB_VERSION}/oauth/access_token`,
    clientId: process.env.FACEBOOK_CLIENT_ID,
    clientSecret: process.env.FACEBOOK_CLIENT_SECRET,
    scopes: ['public_profile', 'email', 'pages_show_list', 'pages_manage_posts', 'publish_video'],
  },
  // Instagram publishes through the Facebook Graph API, so it reuses the same app.
  INSTAGRAM: {
    authorizeUrl: `https://www.facebook.com/${FB_VERSION}/dialog/oauth`,
    tokenUrl: `https://graph.facebook.com/${FB_VERSION}/oauth/access_token`,
    clientId: process.env.FACEBOOK_CLIENT_ID,
    clientSecret: process.env.FACEBOOK_CLIENT_SECRET,
    scopes: [
      'public_profile',
      'pages_show_list',
      'pages_read_engagement',
      'instagram_basic',
      'instagram_content_publish',
    ],
  },
  LINKEDIN: {
    authorizeUrl: 'https://www.linkedin.com/oauth/v2/authorization',
    tokenUrl: 'https://www.linkedin.com/oauth/v2/accessToken',
    clientId: process.env.LINKEDIN_CLIENT_ID,
    clientSecret: process.env.LINKEDIN_CLIENT_SECRET,
    scopes: ['openid', 'profile', 'email', 'w_member_social'],
  },
  X: {
    authorizeUrl: 'https://x.com/i/oauth2/authorize',
    tokenUrl: 'https://api.x.com/v2/oauth2/token',
    clientId: process.env.X_CLIENT_ID,
    clientSecret: process.env.X_CLIENT_SECRET,
    scopes: ['users.read', 'media.write', 'offline.access'],
    pkce: true,
    basicAuth: true,
  },
};

export function isConfigured(platform: SocialPlatformId): boolean {
  const cfg = OAUTH[platform];
  return Boolean(cfg.clientId && cfg.clientSecret);
}

export function buildAuthorizeUrl(
  platform: SocialPlatformId,
  state: string,
  redirectUri: string,
  codeChallenge?: string,
): string {
  const cfg = OAUTH[platform];
  if (!cfg.clientId) {
    throw new PublishError(`${platform} is not configured on this instance.`, {
      code: 'platform_not_configured',
    });
  }
  const params = new URLSearchParams({
    client_id: cfg.clientId,
    redirect_uri: redirectUri,
    response_type: 'code',
    state,
    scope: cfg.scopes.join(' '),
    ...(cfg.extraAuthorizeParams ?? {}),
  });
  if (cfg.pkce && codeChallenge) {
    params.set('code_challenge', codeChallenge);
    params.set('code_challenge_method', 'S256');
  }
  return `${cfg.authorizeUrl}?${params.toString()}`;
}

export interface TokenResponse {
  access_token: string;
  refresh_token?: string;
  expires_in?: number;
  token_type?: string;
  scope?: string;
  // Platform-specific error shapes.
  error?: string;
  error_description?: string;
  error_code?: string;
  error_message?: string;
}

/** Standard authorization-code exchange, with per-platform auth quirks handled. */
export async function exchangeAuthorizationCode(
  platform: SocialPlatformId,
  code: string,
  redirectUri: string,
  codeVerifier?: string,
): Promise<TokenResponse> {
  const cfg = OAUTH[platform];
  const body = new URLSearchParams({
    grant_type: 'authorization_code',
    code,
    redirect_uri: redirectUri,
  });
  if (!cfg.basicAuth) {
    body.set('client_id', cfg.clientId ?? '');
    body.set('client_secret', cfg.clientSecret ?? '');
  }
  if (cfg.pkce && codeVerifier) body.set('code_verifier', codeVerifier);

  const headers: Record<string, string> = {
    'content-type': 'application/x-www-form-urlencoded',
    accept: 'application/json',
  };
  if (cfg.basicAuth) {
    headers.authorization = `Basic ${Buffer.from(
      `${cfg.clientId ?? ''}:${cfg.clientSecret ?? ''}`,
    ).toString('base64')}`;
  }

  const res = await fetch(cfg.tokenUrl, { method: 'POST', headers, body });
  const json = (await res.json().catch(() => ({}))) as TokenResponse;
  if (!res.ok || !json.access_token) {
    const detail = json.error_description ?? json.error_message ?? json.error ?? `HTTP ${res.status}`;
    throw new PublishError(`Could not exchange the ${platform} authorization code.`, {
      code: 'oauth_exchange_failed',
      status: res.status,
      logDetail: detail,
    });
  }
  return json;
}

export function refreshAccessToken(
  platform: SocialPlatformId,
  refreshToken: string,
): Promise<TokenResponse> {
  const cfg = OAUTH[platform];
  const body = new URLSearchParams({
    grant_type: 'refresh_token',
    refresh_token: refreshToken,
  });
  const headers: Record<string, string> = {
    'content-type': 'application/x-www-form-urlencoded',
    accept: 'application/json',
  };
  if (cfg.basicAuth) {
    headers.authorization = `Basic ${Buffer.from(
      `${cfg.clientId ?? ''}:${cfg.clientSecret ?? ''}`,
    ).toString('base64')}`;
  } else {
    body.set('client_id', cfg.clientId ?? '');
    body.set('client_secret', cfg.clientSecret ?? '');
  }
  return fetch(cfg.tokenUrl, { method: 'POST', headers, body }).then(async (res) => {
    const json = (await res.json().catch(() => ({}))) as TokenResponse;
    if (!res.ok || !json.access_token) {
      throw new PublishError(`Could not refresh the ${platform} token.`, {
        code: 'oauth_refresh_failed',
        status: res.status,
        logDetail: json.error_description ?? json.error ?? `HTTP ${res.status}`,
      });
    }
    return json;
  });
}

export function expiresInDate(expiresIn?: number): Date | null {
  if (!expiresIn) return null;
  // Refresh 60s early so an in-flight upload does not race expiry.
  return new Date(Date.now() + (expiresIn - 60) * 1000);
}

export function randomState(): string {
  return randomBytes(24).toString('base64url');
}
