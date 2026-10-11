import { createHash, randomBytes } from 'node:crypto';
import { getServerSession } from 'next-auth/next';
import { NextResponse } from 'next/server';

import { authOptions } from '@/lib/auth';
import { env } from '@/lib/env';
import { getPublisher, isPlatform } from '@/lib/publishing';
import { OAUTH, randomState } from '@/lib/publishing/oauth';
import { appBase, redirectUriFor } from '@/lib/publishing/redirect';

export const dynamic = 'force-dynamic';

const COOKIE = 'viralcut_oauth';

/** Begin an OAuth connection. Bounces the user to the platform's consent screen. */
export async function GET(request: Request, { params }: { params: Promise<{ platform: string }> }) {
  const { platform: raw } = await params;
  const platform = raw.toUpperCase();
  const settingsUrl = `${appBase(request)}/settings`;

  const session = await getServerSession(authOptions);
  if (!session?.user) return NextResponse.redirect(`${settingsUrl.replace('/settings', '/login')}`);
  if (!isPlatform(platform)) return NextResponse.redirect(`${settingsUrl}?error=unknown_platform`);

  const publisher = getPublisher(platform);
  if (!publisher.configured()) {
    // Tell the user what is missing instead of sending them to a broken consent page.
    return NextResponse.redirect(`${settingsUrl}?error=not_configured&platform=${platform}`);
  }

  const state = randomState();
  let codeVerifier: string | undefined;
  let codeChallenge: string | undefined;
  if (OAUTH[platform as keyof typeof OAUTH]?.pkce) {
    codeVerifier = randomBytes(32).toString('base64url');
    codeChallenge = createHash('sha256').update(codeVerifier).digest('base64url');
  }

  const url = publisher.authorizeUrl(state, redirectUriFor(request, platform), codeChallenge);

  const response = NextResponse.redirect(url);
  // The verifier has to survive the round trip and must never reach JS.
  response.cookies.set(
    COOKIE,
    JSON.stringify({ platform, state, codeVerifier, userId: (session.user as { id?: string }).id }),
    { httpOnly: true, sameSite: 'lax', secure: request.url.startsWith('https'), path: '/', maxAge: 600 },
  );
  return response;
}
