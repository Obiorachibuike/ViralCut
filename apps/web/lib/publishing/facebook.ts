/**
 * Facebook Page video publishing via the Graph API.
 *
 * A Page (not a personal profile) is the publishable entity, so the callback
 * resolves the user's Pages and stores the chosen Page's own access token. The
 * user token is exchanged for a long-lived one first so Page tokens survive.
 *
 * Requires a Meta app with `pages_manage_posts` + `publish_video` approved, and
 * the Page must be linked to the connecting user.
 */
import { readFile } from 'node:fs/promises';

import {
  buildAuthorizeUrl,
  exchangeAuthorizationCode,
  isConfigured,
  OAUTH,
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

const VERSION = process.env.FACEBOOK_API_VERSION ?? 'v21.0';
const GRAPH = `https://graph.facebook.com/${VERSION}`;
const GRAPH_VIDEO = `https://graph-video.facebook.com/${VERSION}`;

interface FbPage {
  id: string;
  name?: string;
  access_token?: string;
  picture?: { data?: { url?: string } };
}

async function fbError(res: Response, fallback: string): Promise<PublishError> {
  const body = (await res.json().catch(() => ({}))) as {
    error?: { message?: string; code?: number; type?: string };
  };
  const message = body?.error?.message ?? `${fallback} (HTTP ${res.status})`;
  const code = body?.error?.code;
  // 190 = invalid/expired token; 102 = no permission for this Page.
  if (code === 190) {
    return new PublishError('Facebook rejected the stored token. Reconnect the account.', {
      code: 'token_invalid',
      status: res.status,
    });
  }
  if (code === 102 || code === 200) {
    return new PublishError('Facebook denied permission to post to this Page. Reconnect and re-grant.', {
      code: 'permission_denied',
      status: res.status,
    });
  }
  return new PublishError(message, { code: 'facebook_error', status: res.status, logDetail: message });
}

/** Trade the short-lived user token for one that lasts ~60 days. */
async function longLivedUserToken(shortToken: string): Promise<string> {
  const url = `${GRAPH}/oauth/access_token?${new URLSearchParams({
    grant_type: 'fb_exchange_token',
    client_id: OAUTH.FACEBOOK.clientId ?? '',
    client_secret: OAUTH.FACEBOOK.clientSecret ?? '',
    fb_exchange_token: shortToken,
  }).toString()}`;
  const res = await fetch(url);
  if (!res.ok) return shortToken; // Non-fatal: the short token still works briefly.
  const body = (await res.json().catch(() => ({}))) as { access_token?: string };
  return body.access_token ?? shortToken;
}

export const facebookPublisher: SocialPublisher = {
  platform: 'FACEBOOK',
  label: 'Facebook',
  setupHint:
    'Create a Meta app, get `pages_manage_posts` and `publish_video` approved, link your Page, and set FACEBOOK_CLIENT_ID / FACEBOOK_CLIENT_SECRET.',

  configured: () => isConfigured('FACEBOOK'),

  authorizeUrl: (state, redirectUri) => buildAuthorizeUrl('FACEBOOK', state, redirectUri),

  async connect(code, redirectUri, _extras): Promise<ConnectedIdentity> {
    const token = await exchangeAuthorizationCode('FACEBOOK', code, redirectUri);
    const userToken = await longLivedUserToken(token.access_token);

    const res = await fetch(
      `${GRAPH}/me/accounts?fields=id,name,access_token,picture&limit=25`,
      { headers: { authorization: `Bearer ${userToken}` } },
    );
    if (!res.ok) throw await fbError(res, 'Could not read your Facebook Pages');
    const body = (await res.json()) as { data?: FbPage[] };
    const pages = body.data ?? [];
    if (pages.length === 0) {
      throw new PublishError(
        'No Facebook Pages found. Publishing to Facebook requires a Page you manage.',
        { code: 'no_page' },
      );
    }
    // Publish to the first managed Page; `options.pageId` can override later.
    const page = pages[0];
    return {
      accessToken: page.access_token ?? userToken,
      refreshToken: null, // Facebook Page tokens do not expire while the user token lives.
      expiresAt: null,
      tokenType: 'Bearer',
      platformUserId: page.id,
      displayName: page.name ?? null,
      username: page.name ?? null,
      avatarUrl: page.picture?.data?.url ?? null,
      scopes: (token.scope ?? '').split(',').filter(Boolean),
      meta: { pages: pages.map((p) => ({ id: p.id, name: p.name })) },
    };
  },

  async publish(token: PlatformToken, input: PublishInput, material: PublishMaterial)
    : Promise<PublishOutcome> {
    const pageId = (input.options?.pageId as string) ?? null;
    if (!pageId) {
      throw new PublishError('No Facebook Page id on this connection. Reconnect the account.', {
        code: 'missing_page',
      });
    }

    const form = new FormData();
    form.set('title', input.title.slice(0, 255));
    form.set('description', (input.description ?? '').slice(0, 63_000));
    // Facebook has no "unlisted"; PRIVATE keeps the post unpublished.
    form.set('published', input.privacy === 'PRIVATE' ? 'false' : 'true');
    if (input.options?.scheduledFor) form.set('scheduled_publish_time', String(input.options.scheduledFor));

    if (material.fileUrl && !material.filePath) {
      form.set('file_url', material.fileUrl);
    } else if (material.filePath) {
      const bytes = await readFile(material.filePath);
      form.set(
        'source',
        new Blob([new Uint8Array(bytes)], { type: material.mimeType ?? 'video/mp4' }),
        'clip.mp4',
      );
    } else {
      throw new PublishError('Facebook publishing needs the rendered clip or a public URL.', {
        code: 'missing_material',
      });
    }

    const res = await fetch(`${GRAPH_VIDEO}/${pageId}/videos`, {
      method: 'POST',
      headers: { authorization: `Bearer ${token.accessToken}` },
      body: form,
    });
    if (!res.ok) throw await fbError(res, 'Facebook rejected the upload');
    const body = (await res.json()) as { id?: string };
    if (!body.id) {
      throw new PublishError('Facebook accepted the upload but returned no video id.', {
        code: 'no_video_id',
      });
    }
    return {
      platformPostId: body.id,
      platformUrl: `https://www.facebook.com/${pageId}/videos/${body.id}`,
      // Facebook transcodes after accepting; the id is valid immediately.
      status: 'PROCESSING',
      raw: { pageId },
    };
  },
};
