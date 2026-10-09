import { json, route, HttpError } from '@/lib/api';
import { prisma } from '@/lib/db';
import { getQueue } from '@/lib/queue';

export const POST = route(async ({ userId, params }, req) => {
  const clip = await (prisma as any).clip.findFirst({ where: { id: params.id, video: { project: { userId } } } });
  if (!clip) throw new HttpError('Clip not found', 404);
  const options = await req.json().catch(() => ({}));

  await (prisma as any).clip.update({ where: { id: clip.id }, data: { status: 'RENDERING', renderOptions: { ...(clip.renderOptions ?? {}), ...options } } });

  const jobId = crypto.randomUUID();
  await (prisma as any).job.create({ data: { id: jobId, userId, videoId: clip.videoId, type: 'render-clip', status: 'QUEUED', payload: { clipId: clip.id, options } } });
  await getQueue().enqueue('render-clip', { jobId, userId, videoId: clip.videoId, clipId: clip.id, options });

  return json({ jobId, clipId: clip.id }, { status: 202 });
});
