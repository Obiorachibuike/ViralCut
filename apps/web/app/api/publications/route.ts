import { json, route } from '@/lib/api';
import { prisma } from '@/lib/db';

export const GET = route(async ({ userId }, req) => {
  const url = new URL(req.url);
  const clipId = url.searchParams.get('clipId');
  const publications = await (prisma as any).publication.findMany({
    where: { userId, ...(clipId ? { clipId } : {}) },
    include: {
      account: { select: { id: true, platform: true, displayName: true, username: true, avatarUrl: true, status: true } },
      clip: { select: { id: true, title: true, thumbKey: true, aspectRatio: true } },
    },
    orderBy: { createdAt: 'desc' },
    take: 100,
  });
  return json({ publications });
});
