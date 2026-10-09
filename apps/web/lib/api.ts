import { getServerSession } from 'next-auth/next';
import { NextResponse } from 'next/server';

import { authOptions } from './auth';

export function json(data: unknown, init?: ResponseInit) {
  return NextResponse.json(data, init);
}

export function err(message: string, status = 400, code?: string) {
  return NextResponse.json({ error: { message, code } }, { status });
}

/** Resolves the session user id, or null when unauthenticated. */
export async function currentUserId(): Promise<string | null> {
  const session = await getServerSession(authOptions);
  return (session?.user as { id?: string } | undefined)?.id ?? null;
}

/** Guard: returns the user id or throws a 401 the caller converts. */
export async function requireUser(): Promise<string> {
  const id = await currentUserId();
  if (!id) throw new HttpError('Unauthorized', 401);
  return id;
}

export class HttpError extends Error {
  constructor(message: string, readonly status = 400, readonly code?: string) {
    super(message);
  }
}

/** Wrap a route handler: injects userId + resolved params, maps errors to JSON. */
export function route(
  handler: (ctx: { userId: string; params: Record<string, string> }, req: Request) => Promise<Response>,
) {
  return async (req: Request, context: { params: Promise<Record<string, string>> }) => {
    try {
      const userId = await requireUser();
      const params = context?.params ? await context.params : {};
      return await handler({ userId, params }, req);
    } catch (error) {
      if (error instanceof HttpError) return err(error.message, error.status, error.code);
      const message = error instanceof Error ? error.message : 'Internal error';
      console.error('[api]', error);
      return err(message, 500, 'internal_error');
    }
  };
}
