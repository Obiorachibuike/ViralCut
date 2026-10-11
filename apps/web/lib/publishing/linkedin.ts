/**
 * LinkedIn video posting via the REST (Versioned) API.
 *
 * Three steps, all required: initialize the upload to get a resumable URL and a
 * video URN, PUT the bytes, then create a post referencing that URN. LinkedIn
 * transcodes after the post exists, so the post id comes back immediately.
 *
 * Requires a LinkedIn app with the "Share on LinkedIn" + "Sign In with LinkedIn
 * using OpenID Connect" products.
 */
import { readFile } from 'node:fs/promises';

import {
  buildAuthorizeUrl,
  exchangeAuthorizationCode,
  expiresInDate,
  isConfigured,
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

const API = 'https://api.linkedin.com';
/** Pin the API version so behaviour does not shift under us. */
const HEADERS = {
  'linkedin-version': process.env.LINKEDIN_API_VERSION ?? '202405',
  'x-restli-protocol-version': '2.0.0',
};

async function liError(res: Response, fallback: string): Promise<PublishError> {
  const body = (await res.json().catch(() => ({}))) as { message?: string; status?: number };
  const message = body?.message ?? `${fallback} (HTTP ${res.status})`;
  if (res.status === 401) {
    return new PublishError('LinkedIn rejected the stored token. Reconnect the account.', {
      code: 'token_invalid',
      status: 401,
    });
  }
  if (res.status === 429) {
    return new PublishError('LinkedIn rate limit reached. Try again shortly.', {
      code: 'rate_limited',
      status: 429,
      retryable: true,
    });
  }
  return new PublishError(message, { code: 'linkedin_error', status: res.status, logDetail: message });
}

export const linkedinPublisher: SocialPublisher = {
  platform: 'LINKEDIN',
  label: 'LinkedIn',
  setupHint:
    'Create a LinkedIn app, enable "Share on LinkedIn" and "Sign In with LinkedIn using OpenID Connect", and set LINKEDIN_CLIENT_ID / LINKEDIN_CLIENT_SECRET.',

  configured: () => isConfigured('LINKEDIN'),

  authorizeUrl: (state, redirectUri) => buildAuthorizeUrl('LINKEDIN', state, redirectUri),

  async connect(code, redirectUri, _extras): Promise<ConnectedIdentity> {
    const token = await exchangeAuthorizationCode('LINKEDIN', code, redirectUri);
    const res = await fetch(`${API}/v2/userinfo`, {
      headers: { authorization: `Bearer ${token.access_token}` },
    });
    if (!res.ok) throw await liError(res, 'Could not read the LinkedIn profile');
    const profile = (await res.json()) as {
      sub?: string;
      name?: string;
      picture?: string;
      email?: string;
    };
    if (!profile.sub) {
      throw new PublishError('LinkedIn did not return a user id.', { code: 'no_user' });
    }
    return {
      accessToken: token.access_token,
      refreshToken: token.refresh_token ?? null,
      expiresAt: expiresInDate(token.expires_in),
      tokenType: token.token_type ?? 'Bearer',
      platformUserId: profile.sub,
      displayName: profile.name ?? null,
      username: profile.email ?? null,
      avatarUrl: profile.picture ?? null,
      scopes: (token.scope ?? '').split(' ').filter(Boolean),
    };
  },

  async refresh(token: PlatformToken): Promise<PlatformToken> {
    if (!token.refreshToken) {
      throw new PublishError('This LinkedIn token cannot be refreshed. Reconnect the account.', {
        code: 'no_refresh_token',
      });
    }
    const next = await refreshAccessToken('LINKEDIN', token.refreshToken);
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
      throw new PublishError('LinkedIn publishing needs the rendered clip file.', {
        code: 'missing_file',
      });
    }
    const bytes = await readFile(material.filePath);
    const personId = (input.options?.personId as string) ?? null;
    if (!personId) {
      throw new PublishError('No LinkedIn member id on this connection. Reconnect the account.', {
        code: 'missing_member',
      });
    }
    const memberUrn = `urn:li:person:${personId}`;

    // 1. Initialise the upload.
    const initRes = await fetch(`${API}/rest/videos?action=initializeUpload`, {
      method: 'POST',
      headers: {
        authorization: `Bearer ${token.accessToken}`,
        'content-type': 'application/json',
        ...HEADERS,
      },
      body: JSON.stringify({
        initializeUploadRequest: {
          owner: memberUrn,
          fileSize: bytes.byteLength,
          uploadCaptions: false,
        },
      }),
    });
    if (!initRes.ok) throw await liError(initRes, 'Could not start the LinkedIn upload');
    const init = (await initRes.json()) as {
      value?: { uploadUrl?: string; video?: string };
    };
    const uploadUrl = init.value?.uploadUrl;
    const videoUrn = init.value?.video;
    if (!uploadUrl || !videoUrn) {
      throw new PublishError('LinkedIn did not return an upload target.', { code: 'no_upload_target' });
    }

    // 2. PUT the bytes.
    const putRes = await fetch(uploadUrl, {
      method: 'PUT',
      headers: {
        authorization: `Bearer ${token.accessToken}`,
        'content-type': 'application/octet-stream',
        ...HEADERS,
      },
      body: new Uint8Array(bytes),
    });
    if (!putRes.ok) throw await liError(putRes, 'LinkedIn rejected the upload');

    // 3. Create the post referencing the video URN.
    const commentary = `${input.title}\n\n${input.description ?? ''}`.trim().slice(0, 3000);
    const postRes = await fetch(`${API}/rest/posts`, {
      method: 'POST',
      headers: {
        authorization: `Bearer ${token.accessToken}`,
        'content-type': 'application/json',
        ...HEADERS,
      },
      body: JSON.stringify({
        author: memberUrn,
        commentary,
        visibility: input.privacy === 'PRIVATE' ? 'CONNECTIONS' : 'PUBLIC',
        distribution: { feedDistribution: 'MAIN_FEED' },
        content: { media: { id: videoUrn, title: input.title.slice(0, 200) } },
        isReshareDisabledByAuthor: true,
      }),
    });
    if (!postRes.ok) throw await liError(postRes, 'Could not create the LinkedIn post');
    const post = (await postRes.json()) as { id?: string };
    if (!post.id) {
      throw new PublishError('LinkedIn did not return a post id.', { code: 'no_post_id' });
    }

    return {
      platformPostId: post.id,
      platformUrl: null,
      status: 'PROCESSING',
      raw: { videoUrn },
    };
  },
};
