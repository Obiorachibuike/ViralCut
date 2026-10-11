import { getServerSession } from 'next-auth/next';

import { authOptions } from './auth';

/** Returns the session's user id or throws; keeps every route ownership-safe. */
export async function getUserId(): Promise<string> {
  const session = await getServerSession(authOptions);
  const id = (session?.user as { id?: string } | undefined)?.id;
  if (!id) {
    const err = new Error('Unauthorized') as Error & { status?: number };
    err.status = 401;
    throw err;
  }
  return id;
}
