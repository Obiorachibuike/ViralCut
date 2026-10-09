import { json, route, HttpError } from '@/lib/api';
import { prisma } from '@/lib/db';

export const GET = route(async ({ userId, params }) => {
  const video = await (prisma as any).video.findFirst({ where: { id: params.id, project: { userId } } });
  if (!video) throw new HttpError('Video not found', 404);
  const moments = await (prisma as any).moment.findMany({ where: { videoId: video.id }, orderBy: { rank: 'asc' } });
  return json({ moments });
});
