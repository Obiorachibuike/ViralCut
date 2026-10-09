import { json, route } from '@/lib/api';
import { prisma } from '@/lib/db';

export const GET = route(async ({ userId }, req) => {
  const videoId = new URL(req.url).searchParams.get('videoId');
  const clips = await (prisma as any).clip.findMany({
    where: { video: { project: { userId } }, ...(videoId ? { videoId } : {}) },
    orderBy: { createdAt: 'desc' },
    include: { moment: true },
  });
  return json({ clips });
});
