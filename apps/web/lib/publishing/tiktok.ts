/**
 * TikTok publishing via the Content Posting API (v2).
 *
 * Flow: init a publish, PUT the file in chunks to the returned upload URL, then
 * poll the publish-status endpoint until TikTok reports success. TikTok has no
 * "unlisted" state, so UNLISTED maps to SELF_ONLY and we tell the user.
 *
 * Requires a TikTok developer app with the Content Posting API product approved
 * (public posting needs an audit) — see README.
 */
import { readFile } from 'node:fs/promises';

import { expiresInDate, isConfigured, OAUTH } from './oauth';
import {
  PublishError,
  type ConnectedIdentity,
  type PlatformToken,
  type PublishInput,
  type PublishMaterial,
  type PublishOutcome,
  type SocialPublisher,
} from './types';

const API = 'https://open.tiktokapis.com/v2';
const MAX_CHUNK_BYTES = 64 * 1024 * 1024;

/** TikTok's privacy vocabulary. */
const PRIVACY = {
  PUBLIC: 'PUBLIC_TO_EVERYONE',
  UNLISTED: 'SELF_ONLY',
  PRIVATE: 'SELF_ONLY',
} as const;

async function tiktokError(res: Response, fallback: string): Promise<PublishError> {
  const body = (await res.json().catch(() => ({}))) as {
    error?: { code?: string; message?: string; log_id?: string };
  };
  const message = body?.error?.message ?? `${fallback} (HTTP ${res.status})`;
  const code = body?.error?.code ?? 'tiktok_error';
  if (code === 'access_token_invalid') {
    return new PublishError('TikTok rejected the stored token. Reconnect the account.', {
      code: 'token_invalid',
      status: res.status,
      logDetail: body?.error?.log_id,
    });
  }
  if (code === 'rate_limit_exceeded') {
    return new PublishError('TikTok rate limit reached. Try again shortly.', {
      code: 'rate_limited',
      status: 429,
      retryable: true,
      logDetail: body?.error?.log_id,
    });
  }
  return new PublishError(message, { code, status: res.status, logDetail: body?.error?.log_id });
}

async function tokenRequest(payload: Record<string, string>) {
  const res = await fetch(OAUTH.TIKTOK.tokenUrl, {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded', accept: 'application/json' },
    body: new URLSearchParams({
      client_key: OAUTH.TIKTOK.clientId ?? '',
      client_secret: OAUTH.TIKTOK.clientSecret ?? '',
      ...payload,
    }),
  });
  const json = (await res.json().catch(() => ({}))) as Record<string, unknown>;
  if (!res.ok || !json.access_token) {
    throw new PublishError('Could not complete the TikTok authorization.', {
      code: 'oauth_exchange_failed',
      status: res.status,
      logDetail: JSON.stringify(json).slice(0, 400),
    });
  }
  return json as {
    access_token: string;
    refresh_token?: string;
    expires_in?: number;
    open_id?: string;
    scope?: string;
  };
}

export const tiktokPublisher: SocialPublisher = {
  platform: 'TIKTOK',
  label: 'TikTok',
  setupHint:
    'Create a TikTok developer app, add the Content Posting API product, pass its audit for public posting, and set TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET.',

  configured: () => isConfigured('TIKTOK'),

  authorizeUrl: (state, redirectUri) =>
    `${OAUTH.TIKTOK.authorizeUrl}?${new URLSearchParams({
      client_key: OAUTH.TIKTOK.clientId ?? '',
      redirect_uri: redirectUri,
      response_type: 'code',
      state,
      scope: OAUTH.TIKTOK.scopes.join(','),
    }).toString()}`,

  async connect(code, redirectUri, _extras): Promise<ConnectedIdentity> {
    const token = await tokenRequest({ grant_type: 'authorization_code', code, redirect_uri: redirectUri });

    const res = await fetch(`${API}/user/info/?fields=open_id,union_id,display_name,avatar_url`, {
      headers: { authorization: `Bearer ${token.access_token}` },
    });
    if (!res.ok) throw await tiktokError(res, 'Could not read the TikTok profile');
    const body = (await res.json()) as {
      data?: { user?: { open_id?: string; display_name?: string; avatar_url?: string }; creator_avatar_url?: string };
    };
    const openId = body.data?.user?.open_id ?? token.open_id;
    if (!openId) {
      throw new PublishError('TikTok did not return an account id.', { code: 'no_account' });
    }
    return {
      accessToken: token.access_token,
      refreshToken: token.refresh_token ?? null,
      expiresAt: expiresInDate(token.expires_in),
      tokenType: 'Bearer',
      platformUserId: openId,
      displayName: body.data?.user?.display_name ?? null,
      avatarUrl: body.data?.user?.avatar_url ?? null,
      scopes: (token.scope ?? '').split(/[,\s]+/).filter(Boolean),
    };
  },

  async refresh(token: PlatformToken): Promise<PlatformToken> {
    if (!token.refreshToken) {
      throw new PublishError('This TikTok token cannot be refreshed. Reconnect the account.', {
        code: 'no_refresh_token',
      });
    }
    const next = await tokenRequest({
      grant_type: 'refresh_token',
      refresh_token: token.refreshToken,
    });
    return {
      accessToken: next.access_token,
      refreshToken: next.refresh_token ?? token.refreshToken,
      expiresAt: expiresInDate(next.expires_in),
      tokenType: 'Bearer',
    };
  },

  async publish(token: PlatformToken, input: PublishInput, material: PublishMaterial)
    : Promise<PublishOutcome> {
    // TikTok pulls from a URL or accepts a chunked file upload. Prefer the file
    // so a private render never needs a public link.
    const useFile = Boolean(material.filePath);
    if (!useFile && !material.fileUrl) {
      throw new PublishError('TikTok publishing needs the rendered clip or a public URL.', {
        code: 'missing_material',
      });
    }
    const bytes = useFile ? await readFile(material.filePath!) : null;

    const postInfo: Record<string, unknown> = {
      title: `${input.title} ${input.description ?? ''}`.trim().slice(0, 2200),
      privacy_level: PRIVACY[input.privacy],
      disable_duet: Boolean(input.options?.disableDuet),
      disable_comment: Boolean(input.options?.disableComments),
      disable_stitch: Boolean(input.options?.disableStitch),
      video_cover_timestamp_ms: Number(input.options?.coverTimestampMs ?? 1000),
    };

    const sourceInfo = bytes
      ? {
          source: 'FILE_UPLOAD',
          video_size: bytes.byteLength,
          chunk_size: chunkSizeFor(bytes.byteLength),
          total_chunk_count: totalChunksFor(bytes.byteLength),
        }
      : { source: 'PULL_FROM_URL', video_url: material.fileUrl };

    const init = await fetch(`${API}/post/publish/video/init/`, {
      method: 'POST',
      headers: {
        authorization: `Bearer ${token.accessToken}`,
        'content-type': 'application/json; charset=UTF-8',
      },
      body: JSON.stringify({ post_info: postInfo, source_info: sourceInfo }),
    });
    if (!init.ok) throw await tiktokError(init, 'Could not start the TikTok upload');
    const initBody = (await init.json()) as {
      data?: { publish_id?: string; upload_url?: string };
    };
    const publishId = initBody.data?.publish_id;
    if (!publishId) {
      throw new PublishError('TikTok did not return a publish id.', { code: 'no_publish_id' });
    }

    if (bytes && initBody.data?.upload_url) {
      await uploadChunks(initBody.data.upload_url, bytes, token.accessToken);
    }

    const finalState = await pollPublishStatus(publishId, token.accessToken);
    return {
      platformPostId: finalState.postId ?? publishId,
      platformUrl: null,
      status: finalState.status === 'PUBLISH_COMPLETE' ? 'PUBLISHED' : 'PROCESSING',
      raw: finalState.raw,
    };
  },
};

function chunkSizeFor(size: number): number {
  return Math.ceil(size / totalChunksFor(size));
}

function totalChunksFor(size: number): number {
  if (size <= MAX_CHUNK_BYTES) return 1;
  return Math.min(64, Math.ceil(size / MAX_CHUNK_BYTES));
}

async function uploadChunks(url: string, bytes: Buffer, accessToken: string) {
  const total = bytes.byteLength;
  const chunks = totalChunksFor(total);
  const size = chunkSizeFor(total);
  for (let i = 0; i < chunks; i += 1) {
    const start = i * size;
    const end = Math.min(total, start + size) - 1;
    const slice = bytes.subarray(start, end + 1);
    const res = await fetch(url, {
      method: 'PUT',
      headers: {
        authorization: `Bearer ${accessToken}`,
        'content-range': `bytes ${start}-${end}/${total}`,
        'content-length': String(slice.byteLength),
        'content-type': 'video/mp4',
      },
      body: new Uint8Array(slice),
    });
    if (!res.ok) throw await tiktokError(res, `TikTok chunk ${i + 1}/${chunks} failed`);
  }
}

async function pollPublishStatus(
  publishId: string,
  accessToken: string,
  timeoutMs = 10 * 60_000,
): Promise<{ status: string; postId: string | null; raw: unknown }> {
  const deadline = Date.now() + timeoutMs;
  let last: Record<string, unknown> = {};
  while (Date.now() < deadline) {
    const res = await fetch(`${API}/post/publish/status/fetch/`, {
      method: 'POST',
      headers: { authorization: `Bearer ${accessToken}`, 'content-type': 'application/json' },
      body: JSON.stringify({ publish_id: publishId }),
    });
    if (res.ok) {
      const body = (await res.json()) as { data?: { status?: string; publicaly_available_post_id?: string[] } };
      last = (body.data ?? {}) as Record<string, unknown>;
      const status = String(body.data?.status ?? '');
      if (status === 'PUBLISH_COMPLETE') {
        return {
          status,
          postId: body.data?.publicaly_available_post_id?.[0] ?? publishId,
          raw: last,
        };
      }
      if (status === 'FAILED') {
        throw new PublishError('TikTok rejected the video during processing.', {
          code: 'publish_failed',
          logDetail: JSON.stringify(last).slice(0, 400),
        });
      }
    }
    await new Promise((r) => setTimeout(r, 5000));
  }
  // Not a failure: TikTok can finish after we stop waiting.
  return { status: 'PROCESSING', postId: publishId, raw: last };
}
