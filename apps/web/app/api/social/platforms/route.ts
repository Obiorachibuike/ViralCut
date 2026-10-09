import { NextResponse } from 'next/server';

import { describePlatforms } from '@/lib/publishing';

/** Which networks this instance can actually connect, and what is missing. */
export async function GET() {
  return NextResponse.json({ platforms: describePlatforms() });
}
