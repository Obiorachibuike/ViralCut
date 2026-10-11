import { NextResponse } from 'next/server';

import { media } from '@/lib/media';

/** Pass the engine's honest capability report through to the generate UI. */
export async function GET() {
  try {
    return NextResponse.json(await media.t2vProviders());
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Media engine unavailable';
    return NextResponse.json({ active: null, activeConfigured: false, providers: [], error: message });
  }
}
