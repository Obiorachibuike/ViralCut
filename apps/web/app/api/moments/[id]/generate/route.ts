import { json, route, HttpError } from '@/lib/api';
import { prisma } from '@/lib/db';
import { getQueue } from '@/lib/queue';

export const POST = route(async ({ userId, params }, req) => {
  const moment = await (prisma as any).moment.findFirst({ where: { id: params.id, video: { project: { userId } } } });
  if (!moment) throw new HttpError('Moment not found', 404);
  const body = await req.json().catch(() => ({}));

  const clip = await (prisma as any).clip.create({
    data: {
      videoId: moment.videoId,
      momentId: moment.id,
      title: moment.title,
      startMs: moment.startMs,
      endMs: moment.endMs,
      aspectRatio: body.aspectRatio ?? '9:16',
      captionStyle: body.captionStyle ?? 'CREATOR',
      status: 'GENERATING',
      viralScore: moment.viralScore,
      categories: moment.categories ?? [],
      hook: moment.hook ?? null,
      scores: moment.scores ?? {},
      renderOptions: { captionStyle: body.captionStyle ?? 'CREATOR', reframeMode: body.reframeMode ?? 'AUTO' },
    },
  });

  const jobId = crypto.randomUUID();
  await (prisma as any).job.create({ data: { id: jobId, userId, videoId: moment.videoId, type: 'render-clip', status: 'QUEUED', payload: { clipId: clip.id } } });
  await getQueue().enqueue('render-clip', { jobId, userId, videoId: moment.videoId, clipId: clip.id, momentId: moment.id });

  return json({ clip, jobId }, { status: 201 });
});
