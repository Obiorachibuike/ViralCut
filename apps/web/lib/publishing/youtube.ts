/**
 * YouTube publishing via the Data API v3 resumable upload.
 *
 * Flow: start a resumable session with the video metadata, PUT the bytes to the
 * session URI, read back the video id. Privacy maps straight onto YouTube's
 * privacyStatus, so "unlisted" behaves the way users expect.
 *
 * Requires a Google Cloud OAuth client with the YouTube Data API enabled.
 */
import { readFile } from 'node:fs/promises';

import {
  exchangeAuthorizationCode,
  expiresInDate,
  isConfigured,
  buildAuthorizeUrl,
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

const API = 'https://www.googleapis.com';

const PRIVACY = { PUBLIC: 'public', UNLISTED: 'unlisted', PRIVATE: 'private' } as const;

async function parseError(res: Response): Promise<PublishError> {
  const body = (await res.json().catch(() => ({}))) as { error?: { message?: string } };
  const message = body?.error?.message ?? `YouTube returned HTTP ${res.status}`;
  // 401/403 usually mean the token expired or the quota is gone — both are
  // things the user can act on, so surface them distinctly.
  if (res.status === 401) {
    return new PublishError('YouTube rejected the stored token. Reconnect the account.', {
      code: 'token_invalid',
      status: 401,
      retryable: false,
    });
  }
  if (res.status === 403 && /quota/i.test(message)) {
    return new PublishError('YouTube daily upload quota exceeded. Try again tomorrow.', {
      code: 'quota_exceeded',
      status: 403,
      retryable: true,
    });
  }
  return new PublishError(message, { code: 'youtube_error', status: res.status, logDetail: message });
}

export const youtubePublisher: SocialPublisher = {
  platform: 'YOUTUBE',
  label: 'YouTube',
  setupHint:
    'Create an OAuth client in Google Cloud Console, enable the YouTube Data API v3, and set YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET.',

  configured: () => isConfigured('YOUTUBE'),

  authorizeUrl: (state, redirectUri) => buildAuthorizeUrl('YOUTUBE', state, redirectUri),

  async connect(code, redirectUri, _extras): Promise<ConnectedIdentity> {
    const token = await exchangeAuthorizationCode('YOUTUBE', code, redirectUri);
    const res = await fetch(`${API}/youtube/v3/channels?part=snippet&mine=true`, {
      headers: { authorization: `Bearer ${token.access_token}` },
    });
    if (!res.ok) throw await parseError(res);
    const body = (await res.json()) as {
      items?: { id: string; snippet?: { title?: string; customUrl?: string; thumbnails?: Record<string, { url?: string }> } }[];
    };
    const channel = body.items?.[0];
    if (!channel) {
      throw new PublishError('No YouTube channel found for this account.', {
        code: 'no_channel',
      });
    }
    return {
      accessToken: token.access_token,
      refreshToken: token.refresh_token ?? null,
      expiresAt: expiresInDate(token.expires_in),
      tokenType: token.token_type ?? 'Bearer',
      platformUserId: channel.id,
      displayName: channel.snippet?.title ?? null,
      username: channel.snippet?.customUrl ?? null,
      avatarUrl: channel.snippet?.thumbnails?.default?.url ?? null,
      scopes: (token.scope ?? '').split(' ').filter(Boolean),
    };
  },

  async refresh(token: PlatformToken): Promise<PlatformToken> {
    if (!token.refreshToken) {
      throw new PublishError('This YouTube token cannot be refreshed. Reconnect the account.', {
        code: 'no_refresh_token',
      });
    }
    const next = await refreshAccessToken('YOUTUBE', token.refreshToken);
    return {
      accessToken: next.access_token,
      // Google only returns a refresh token on the first consent.
      refreshToken: next.refresh_token ?? token.refreshToken,
      expiresAt: expiresInDate(next.expires_in),
      tokenType: next.token_type ?? 'Bearer',
    };
  },

  async publish(token: PlatformToken, input: PublishInput, material: PublishMaterial)
    : Promise<PublishOutcome> {
    if (!material.filePath) {
      throw new PublishError('YouTube publishing needs the rendered clip file.', {
        code: 'missing_file',
      });
    }
    const bytes = await readFile(material.filePath);

    // YouTube caps the combined tag length at 500 characters.
    const tags = (input.tags ?? []).slice(0, 20);
    let budget = 500;
    const trimmed = tags.filter((t) => {
      if (t.length + 1 > budget) return false;
      budget -= t.length + 1;
      return true;
    });

    const metadata = {
      snippet: {
        title: input.title.slice(0, 100),
        description: (input.description ?? '').slice(0, 5000),
        tags: trimmed,
        categoryId: (input.options?.categoryId as string) ?? '22',
      },
      status: {
        privacyStatus: PRIVACY[input.privacy],
        selfDeclaredMadeForKids: Boolean(input.options?.madeForKids),
        publishAt: input.options?.publishAt as string | undefined,
      },
    };

    const start = await fetch(
      `${API}/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status`,
      {
        method: 'POST',
        headers: {
          authorization: `Bearer ${token.accessToken}`,
          'content-type': 'application/json; charset=UTF-8',
          'x-upload-content-type': material.mimeType ?? 'video/mp4',
          'x-upload-content-length': String(bytes.byteLength),
        },
        body: JSON.stringify(metadata),
      },
    );
    if (!start.ok) throw await parseError(start);
    const sessionUri = start.headers.get('location');
    if (!sessionUri) {
      throw new PublishError('YouTube did not return an upload session URI.', {
        code: 'no_session',
      });
    }

    const upload = await fetch(sessionUri, {
      method: 'PUT',
      headers: {
        authorization: `Bearer ${token.accessToken}`,
        'content-length': String(bytes.byteLength),
        'content-type': material.mimeType ?? 'video/mp4',
      },
      body: new Uint8Array(bytes),
    });
    if (!upload.ok) throw await parseError(upload);

    const created = (await upload.json()) as { id?: string; status?: { uploadStatus?: string } };
    if (!created.id) {
      throw new PublishError('YouTube accepted the upload but returned no video id.', {
        code: 'no_video_id',
      });
    }
    return {
      platformPostId: created.id,
      platformUrl: `https://www.youtube.com/watch?v=${created.id}`,
      // YouTube transcodes before the video is actually watchable.
      status: created.status?.uploadStatus === 'processed' ? 'PUBLISHED' : 'PROCESSING',
      raw: { uploadStatus: created.status?.uploadStatus },
    };
  },
};
