import { err, json, route, HttpError } from '@/lib/api';
import { prisma } from '@/lib/db';
import { getQueue } from '@/lib/queue';

export const POST = route(async ({ userId, params }) => {
  const video = await (prisma as any).video.findFirst({ where: { id: params.id, project: { userId } }, include: { source: true } });
  if (!video) throw new HttpError('Video not found', 404);
  if (!video.storageKey) return err('Video has no media yet; upload a file or import a permitted URL', 409);

  const jobId = crypto.randomUUID();
  await (prisma as any).job.create({
    data: { id: jobId, userId, projectId: video.projectId, videoId: video.id, type: 'analyze-video', status: 'QUEUED', payload: { storageKey: video.storageKey } },
  });
  await getQueue().enqueue('analyze-video', { jobId, userId, videoId: video.id, storageKey: video.storageKey });
  return json({ jobId, videoId: video.id }, { status: 202 });
});
void err;
