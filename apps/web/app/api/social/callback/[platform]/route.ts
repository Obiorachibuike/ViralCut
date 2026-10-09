import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';

import { prisma } from '@/lib/db';
import { encryptToken } from '@/lib/publishing';
import { getPublisher, isPlatform, PublishError } from '@/lib/publishing';
import { safeEqual } from '@/lib/publishing/crypto';
import { appBase, redirectUriFor } from '@/lib/publishing/redirect';

export const dynamic = 'force-dynamic';

const COOKIE = 'viralcut_oauth';

/** OAuth callback: exchange the code, identify the account, store tokens encrypted. */
export async function GET(request: Request, { params }: { params: Promise<{ platform: string }> }) {
  const { platform: raw } = await params;
  const platform = raw.toUpperCase();
  const url = new URL(request.url);
  const settings = `${appBase(request)}/settings`;

  if (!isPlatform(platform)) return NextResponse.redirect(`${settings}?error=unknown_platform`);

  // A platform-side refusal (user clicked "cancel", scope denied, ...).
  const oauthError = url.searchParams.get('error');
  if (oauthError) {
    const detail = url.searchParams.get('error_description') ?? oauthError;
    return NextResponse.redirect(
      `${settings}?error=denied&platform=${platform}&detail=${encodeURIComponent(detail)}`,
    );
  }

  const code = url.searchParams.get('code');
  const state = url.searchParams.get('state');
  const jar = await cookies();
  const stored = jar.get(COOKIE)?.value;
  if (!code || !state || !stored) {
    return NextResponse.redirect(`${settings}?error=missing_state`);
  }

  let parsed: { platform?: string; state?: string; codeVerifier?: string; userId?: string };
  try {
    parsed = JSON.parse(stored);
  } catch {
    return NextResponse.redirect(`${settings}?error=bad_state`);
  }
  // CSRF: the state we set must match the one that came back, constant-time.
  if (!parsed.state || !safeEqual(parsed.state, state) || parsed.platform !== platform) {
    return NextResponse.redirect(`${settings}?error=state_mismatch`);
  }

  const redirectUri = redirectUriFor(request, platform);
  const response = NextResponse.redirect(`${settings}?connected=${platform}`);
  response.cookies.delete(COOKIE);

  try {
    const publisher = getPublisher(platform);
    const identity = await publisher.connect(code, redirectUri, {
      codeVerifier: parsed.codeVerifier ?? '',
    });

    await (prisma as any).socialAccount.upsert({
      where: {
        userId_platform_platformUserId: {
          userId: parsed.userId as string,
          platform,
          platformUserId: identity.platformUserId,
        },
      },
      update: {
        accessToken: encryptToken(identity.accessToken),
        refreshToken: identity.refreshToken ? encryptToken(identity.refreshToken) : null,
        tokenType: identity.tokenType ?? null,
        scopes: identity.scopes,
        expiresAt: identity.expiresAt ?? null,
        username: identity.username ?? null,
        displayName: identity.displayName ?? null,
        avatarUrl: identity.avatarUrl ?? null,
        status: 'CONNECTED',
        meta: identity.meta ?? {},
        lastError: null,
        connectedAt: new Date(),
      },
      create: {
        userId: parsed.userId as string,
        platform,
        platformUserId: identity.platformUserId,
        accessToken: encryptToken(identity.accessToken),
        refreshToken: identity.refreshToken ? encryptToken(identity.refreshToken) : null,
        tokenType: identity.tokenType ?? null,
        scopes: identity.scopes,
        expiresAt: identity.expiresAt ?? null,
        username: identity.username ?? null,
        displayName: identity.displayName ?? null,
        avatarUrl: identity.avatarUrl ?? null,
        meta: identity.meta ?? {},
      },
    });
  } catch (error) {
    // Surface a user-readable reason; keep platform internals in the server log.
    const message = error instanceof PublishError ? error.message : 'Could not complete the connection.';
    if (error instanceof PublishError && error.opts.logDetail) {
      console.error(`[social:${platform}] connect failed`, error.opts.logDetail);
    } else {
      console.error(`[social:${platform}] connect failed`, error);
    }
    return NextResponse.redirect(
      `${settings}?error=connect_failed&platform=${platform}&detail=${encodeURIComponent(message)}`,
    );
  }

  return response;
}
