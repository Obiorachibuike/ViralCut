/**
 * Instagram Reels publishing via the Facebook Graph API.
 *
 * Instagram only accepts a **publicly reachable** video URL (it pulls the file
 * server-side), so this adapter requires a signed URL from storage — a local
 * path is not enough. The account is the Page's linked Instagram *business*
 * account, which is what the content-publishing endpoints operate on.
 *
 * Instagram has no unlisted/private post state: a Reel is either published to a
 * public account or not published at all, so non-public requests are refused
 * with a clear message rather than silently posting.
 */
import {
  buildAuthorizeUrl,
  exchangeAuthorizationCode,
  isConfigured,
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

async function igError(res: Response, fallback: string): Promise<PublishError> {
  const body = (await res.json().catch(() => ({}))) as {
    error?: { message?: string; code?: number; error_subcode?: number };
  };
  const message = body?.error?.message ?? `${fallback} (HTTP ${res.status})`;
  if (body?.error?.code === 190) {
    return new PublishError('Facebook/Instagram rejected the stored token. Reconnect.', {
      code: 'token_invalid',
      status: res.status,
    });
  }
  if (body?.error?.code === 36003) {
    return new PublishError('The video URL could not be downloaded by Instagram.', {
      code: 'url_unreachable',
      status: res.status,
      logDetail: message,
    });
  }
  return new PublishError(message, { code: 'instagram_error', status: res.status, logDetail: message });
}

export const instagramPublisher: SocialPublisher = {
  platform: 'INSTAGRAM',
  label: 'Instagram',
  setupHint:
    'Use the same Meta app as Facebook, get `instagram_content_publish` approved, and connect a Page whose linked Instagram account is a Business or Creator account.',

  configured: () => isConfigured('INSTAGRAM'),

  authorizeUrl: (state, redirectUri) => buildAuthorizeUrl('INSTAGRAM', state, redirectUri),

  async connect(code, redirectUri, _extras): Promise<ConnectedIdentity> {
    const token = await exchangeAuthorizationCode('INSTAGRAM', code, redirectUri);

    const pagesRes = await fetch(`${GRAPH}/me/accounts?fields=id,name,access_token&limit=25`, {
      headers: { authorization: `Bearer ${token.access_token}` },
    });
    if (!pagesRes.ok) throw await igError(pagesRes, 'Could not read your Facebook Pages');
    const pages = (((await pagesRes.json()) as { data?: { id: string; name?: string; access_token?: string }[] })
      .data ?? []);

    // Find the first Page that actually has a linked Instagram business account.
    for (const page of pages) {
      if (!page.access_token) continue;
      const igRes = await fetch(
        `${GRAPH}/${page.id}?fields=instagram_business_account{id,username,profile_picture_url}`,
        { headers: { authorization: `Bearer ${page.access_token}` } },
      );
      if (!igRes.ok) continue;
      const igBody = (await igRes.json()) as {
        instagram_business_account?: { id: string; username?: string; profile_picture_url?: string };
      };
      const ig = igBody.instagram_business_account;
      if (!ig) continue;
      return {
        accessToken: page.access_token,
        refreshToken: null,
        expiresAt: null,
        tokenType: 'Bearer',
        platformUserId: ig.id,
        username: ig.username ?? null,
        displayName: ig.username ? `@${ig.username}` : (page.name ?? null),
        avatarUrl: ig.profile_picture_url ?? null,
        scopes: (token.scope ?? '').split(',').filter(Boolean),
        meta: { pageId: page.id, pageName: page.name },
      };
    }

    throw new PublishError(
      'None of your Facebook Pages has a linked Instagram Business or Creator account.',
      { code: 'no_instagram_account' },
    );
  },

  async publish(token: PlatformToken, input: PublishInput, material: PublishMaterial)
    : Promise<PublishOutcome> {
    if (input.privacy !== 'PUBLIC') {
      throw new PublishError(
        'Instagram Reels can only be published publicly. Choose a different platform for unlisted or private posts.',
        { code: 'privacy_unsupported' },
      );
    }
    if (!material.fileUrl) {
      throw new PublishError(
        'Instagram pulls the video from a public URL. Configure R2 with a public base URL to enable Instagram publishing.',
        { code: 'requires_public_url' },
      );
    }

    const pageId = (input.options?.pageId as string) ?? null;
    if (!pageId) {
      throw new PublishError('No Facebook Page id on this connection. Reconnect the account.', {
        code: 'missing_page',
      });
    }

    const caption = `${input.title}\n\n${input.description ?? ''}`
      .trim()
      .concat((input.tags ?? []).length ? `\n\n${(input.tags ?? []).map((t) => `#${t.replace(/\s+/g, '')}`).join(' ')}` : '')
      .slice(0, 2200);

    const container = new URLSearchParams({
      media_type: 'REELS',
      video_url: material.fileUrl,
      share_to_feed: String(input.options?.shareToFeed ?? true),
    });
    if (caption) container.set('caption', caption);
    if (input.options?.coverUrl) container.set('cover_url', String(input.options.coverUrl));

    const createRes = await fetch(`${GRAPH}/${pageId}/media`, {
      method: 'POST',
      headers: { authorization: `Bearer ${token.accessToken}` },
      body: container,
    });
    if (!createRes.ok) throw await igError(createRes, 'Could not create the Instagram media container');
    const created = (await createRes.json()) as { id?: string };
    if (!created.id) {
      throw new PublishError('Instagram did not return a media container id.', {
        code: 'no_container',
      });
    }

    await waitForContainer(created.id, token.accessToken);

    const publishRes = await fetch(`${GRAPH}/${pageId}/media_publish`, {
      method: 'POST',
      headers: {
        authorization: `Bearer ${token.accessToken}`,
        'content-type': 'application/x-www-form-urlencoded',
      },
      body: new URLSearchParams({ creation_id: created.id }),
    });
    if (!publishRes.ok) throw await igError(publishRes, 'Could not publish the Instagram Reel');
    const published = (await publishRes.json()) as { id?: string };
    if (!published.id) {
      throw new PublishError('Instagram did not return a media id.', { code: 'no_media_id' });
    }

    return {
      platformPostId: published.id,
      platformUrl: null,
      status: 'PUBLISHED',
      raw: { containerId: created.id, pageId },
    };
  },
};

/** Instagram processes the pulled video asynchronously; publishing too early fails. */
async function waitForContainer(containerId: string, accessToken: string, timeoutMs = 5 * 60_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const res = await fetch(`${GRAPH}/${containerId}?fields=status_code,status`, {
      headers: { authorization: `Bearer ${accessToken}` },
    });
    if (res.ok) {
      const body = (await res.json()) as { status_code?: string; status?: string };
      if (body.status_code === 'FINISHED') return;
      if (body.status_code === 'ERROR') {
        throw new PublishError(`Instagram could not process the video: ${body.status ?? 'unknown error'}`, {
          code: 'container_error',
        });
      }
    }
    await new Promise((r) => setTimeout(r, 3000));
  }
  throw new PublishError('Instagram timed out processing the video.', {
    code: 'container_timeout',
    retryable: true,
  });
}
