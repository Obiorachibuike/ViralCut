import { err, json, route, HttpError } from '@/lib/api';
import { prisma } from '@/lib/db';

async function owned(userId: string, id: string) {
  const video = await (prisma as any).video.findFirst({
    where: { id, project: { userId } },
    include: { source: true, moments: { orderBy: { rank: 'asc' } }, clips: true },
  });
  if (!video) throw new HttpError('Video not found', 404);
  return video;
}

export const GET = route(async ({ userId, params }) => json({ video: await owned(userId, params.id) }));

export const DELETE = route(async ({ userId, params }) => {
  await owned(userId, params.id);
  await (prisma as any).video.delete({ where: { id: params.id } });
  return json({ deleted: true });
});
void err;
