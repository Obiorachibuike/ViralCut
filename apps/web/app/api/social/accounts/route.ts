import { json, route, HttpError } from '@/lib/api';
import { prisma } from '@/lib/db';

/**
 * Connected accounts. Tokens are never selected — the browser only ever sees
 * identity metadata it needs to render the list.
 */
export const GET = route(async ({ userId }) => {
  const accounts = await (prisma as any).socialAccount.findMany({
    where: { userId },
    select: {
      id: true,
      platform: true,
      platformUserId: true,
      username: true,
      displayName: true,
      avatarUrl: true,
      scopes: true,
      status: true,
      expiresAt: true,
      connectedAt: true,
      lastUsedAt: true,
      lastError: true,
    },
    orderBy: { connectedAt: 'desc' },
  });
  return json({ accounts });
});

/** Disconnect: DELETE /api/social/accounts?id=... */
export const DELETE = route(async ({ userId }, req) => {
  const id = new URL(req.url).searchParams.get('id');
  if (!id) throw new HttpError('An account id is required', 400);
  const account = await (prisma as any).socialAccount.findFirst({ where: { id, userId } });
  if (!account) throw new HttpError('Account not found', 404);
  await (prisma as any).socialAccount.delete({ where: { id } });
  return json({ deleted: true });
});
