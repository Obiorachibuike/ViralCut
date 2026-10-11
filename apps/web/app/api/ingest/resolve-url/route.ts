import { NextResponse } from 'next/server';

import { media } from '@/lib/media';

/**
 * Public URL preview. Validates + classifies a URL via the media engine's
 * provider detection without touching the database or requiring auth, so the
 * landing demo shows real detection (permitted / private / DRM / login).
 */
export async function POST(request: Request) {
  const body = await request.json().catch(() => ({}));
  const url = typeof body?.url === 'string' ? body.url : '';
  if (!url) return NextResponse.json({ error: 'URL is required' }, { status: 400 });

  try {
    const result = await media.resolveUrl(url);
    return NextResponse.json(result);
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Could not analyze this URL';
    return NextResponse.json({ error: message, permitted: false }, { status: 502 });
  }
}
