/**
 * X (Twitter) publishing via the v2 API.
 *
 * OAuth 2.0 user context with PKCE, so the connect flow needs the code verifier
 * that was generated when we built the authorize URL. Video goes through the
 * chunked media upload (INIT / APPEND / FINALIZE, then STATUS while X transcodes)
 * before the tweet itself references the media id.
 *
 * Requires an X app with OAuth 2.0 user context enabled and `media.write` +
 * `offline.access` scopes.
 */
import { readFile } from 'node:fs/promises';

import {
  buildAuthorizeUrl,
  exchangeAuthorizationCode,
  expiresInDate,
  isConfigured,
  OAUTH,
  refreshAccessToken,
} from './oauth';
import {
  PublishError,
  type ConnectedIdentity,
  type PlatformToken,
  type PublishInput,
  type PublishMaterial,
  type PublishOutcome,
  type SocialPublisher,
} from './types';

const API = 'https://api.x.com/2';
const MEDIA = `${API}/media/upload`;
const CHUNK_BYTES = 4 * 1024 * 1024;

async function xError(res: Response, fallback: string): Promise<PublishError> {
  const body = (await res.json().catch(() => ({}))) as {
    errors?: { message?: string; code?: number }[];
    title?: string;
    detail?: string;
  };
  const message =
    body?.errors?.[0]?.message ?? body?.detail ?? body?.title ?? `${fallback} (HTTP ${res.status})`;
  if (res.status === 401) {
    return new PublishError('X rejected the stored token. Reconnect the account.', {
      code: 'token_invalid',
      status: 401,
    });
  }
  if (res.status === 429) {
    return new PublishError('X rate limit reached. Try again shortly.', {
      code: 'rate_limited',
      status: 429,
      retryable: true,
    });
  }
  return new PublishError(message, { code: 'x_error', status: res.status, logDetail: message });
}

export const xPublisher: SocialPublisher = {
  platform: 'X',
  label: 'X',
  setupHint:
    'Create an X app with OAuth 2.0 user context enabled, then set X_CLIENT_ID / X_CLIENT_SECRET.',

  configured: () => isConfigured('X'),

  authorizeUrl: (state, redirectUri, codeChallenge) =>
    buildAuthorizeUrl('X', state, redirectUri, codeChallenge),

  async connect(code, redirectUri, extras): Promise<ConnectedIdentity> {
    const verifier = extras?.codeVerifier;
    if (!verifier) {
      throw new PublishError('Missing the PKCE verifier for this X authorization.', {
        code: 'missing_verifier',
      });
    }
    const token = await exchangeAuthorizationCode('X', code, redirectUri, verifier);

    const res = await fetch(`${API}/users/me?user.fields=profile_image_url,username`, {
      headers: { authorization: `Bearer ${token.access_token}` },
    });
    if (!res.ok) throw await xError(res, 'Could not read the X profile');
    const body = (await res.json()) as {
      data?: { id?: string; username?: string; name?: string; profile_image_url?: string };
    };
    if (!body.data?.id) {
      throw new PublishError('X did not return a user id.', { code: 'no_user' });
    }
    return {
      accessToken: token.access_token,
      refreshToken: token.refresh_token ?? null,
      expiresAt: expiresInDate(token.expires_in),
      tokenType: token.token_type ?? 'Bearer',
      platformUserId: body.data.id,
      username: body.data.username ?? null,
      displayName: body.data.name ?? null,
      avatarUrl: body.data.profile_image_url ?? null,
      scopes: (token.scope ?? '').split(' ').filter(Boolean),
    };
  },

  async refresh(token: PlatformToken): Promise<PlatformToken> {
    if (!token.refreshToken) {
      throw new PublishError('This X token cannot be refreshed. Reconnect the account.', {
        code: 'no_refresh_token',
      });
    }
    const next = await refreshAccessToken('X', token.refreshToken);
    return {
      accessToken: next.access_token,
      refreshToken: next.refresh_token ?? token.refreshToken,
      expiresAt: expiresInDate(next.expires_in),
      tokenType: next.token_type ?? 'Bearer',
    };
  },

  async publish(token: PlatformToken, input: PublishInput, material: PublishMaterial)
    : Promise<PublishOutcome> {
    if (!material.filePath) {
      throw new PublishError('X publishing needs the rendered clip file.', {
        code: 'missing_file',
      });
    }
    const auth = { authorization: `Bearer ${token.accessToken}` };
    const bytes = await readFile(material.filePath);

    // INIT
    const initRes = await fetch(MEDIA, {
      method: 'POST',
      headers: { ...auth, 'content-type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        command: 'INIT',
        media_type: material.mimeType ?? 'video/mp4',
        total_bytes: String(bytes.byteLength),
        media_category: 'tweet_video',
      }),
    });
    if (!initRes.ok) throw await xError(initRes, 'Could not start the X upload');
    const init = (await initRes.json()) as { data?: { id?: string } };
    const mediaId = init.data?.id;
    if (!mediaId) {
      throw new PublishError('X did not return a media id.', { code: 'no_media_id' });
    }

    // APPEND in chunks
    for (let offset = 0, index = 0; offset < bytes.byteLength; offset += CHUNK_BYTES, index += 1) {
      const slice = bytes.subarray(offset, offset + CHUNK_BYTES);
      const form = new FormData();
      form.set('command', 'APPEND');
      form.set('media_id', mediaId);
      form.set('segment_index', String(index));
      form.set('media', new Blob([new Uint8Array(slice)], { type: 'video/mp4' }), 'clip.mp4');
      const res = await fetch(MEDIA, { method: 'POST', headers: auth, body: form });
      if (!res.ok) throw await xError(res, `X chunk ${index} failed`);
    }

    // FINALIZE
    const finRes = await fetch(MEDIA, {
      method: 'POST',
      headers: { ...auth, 'content-type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ command: 'FINALIZE', media_id: mediaId }),
    });
    if (!finRes.ok) throw await xError(finRes, 'X could not finalise the upload');
    const fin = (await finRes.json()) as {
      data?: { processing_info?: { state?: string; check_after_secs?: number } };
    };

    let processing = true;
    if (fin.data?.processing_info?.state === 'succeeded') processing = false;
    else if (fin.data?.processing_info?.state === 'failed') {
      throw new PublishError('X failed to process the video.', { code: 'processing_failed' });
    }
    while (processing) {
      await new Promise((r) => setTimeout(r, (fin.data?.processing_info?.check_after_secs ?? 5) * 1000));
      const statusRes = await fetch(MEDIA, {
        method: 'POST',
        headers: { ...auth, 'content-type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({ command: 'STATUS', media_id: mediaId }),
      });
      if (!statusRes.ok) throw await xError(statusRes, 'X status check failed');
      const status = (await statusRes.json()) as {
        data?: { processing_info?: { state?: string } };
      };
      const state = status.data?.processing_info?.state;
      if (state === 'succeeded') processing = false;
      if (state === 'failed') {
        throw new PublishError('X failed to process the video.', { code: 'processing_failed' });
      }
    }

    // Post
    const text = `${input.title} ${input.description ?? ''}`.trim().slice(0, 280);
    const tweetRes = await fetch(`${API}/tweets`, {
      method: 'POST',
      headers: { ...auth, 'content-type': 'application/json' },
      body: JSON.stringify({
        text: text || input.title.slice(0, 280),
        media: { media_ids: [mediaId] },
      }),
    });
    if (!tweetRes.ok) throw await xError(tweetRes, 'Could not create the post on X');
    const tweet = (await tweetRes.json()) as { data?: { id?: string } };
    if (!tweet.data?.id) {
      throw new PublishError('X did not return a post id.', { code: 'no_post_id' });
    }

    return {
      platformPostId: tweet.data.id,
      platformUrl: `https://x.com/i/status/${tweet.data.id}`,
      status: 'PUBLISHED',
      raw: { mediaId, oauth: OAUTH.X.scopes },
    };
  },
};
