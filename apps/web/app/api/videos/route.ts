import { detectProvider } from '@viralcut/shared';

import { err, json, route } from '@/lib/api';
import { prisma } from '@/lib/db';
import { getQueue } from '@/lib/queue';

export const GET = route(async ({ userId }) => {
  const videos = await (prisma as any).video.findMany({
    where: { project: { userId } },
    orderBy: { createdAt: 'desc' },
    include: { source: true, _count: { select: { moments: true, clips: true } } },
  });
  return json({ videos });
});

/** Import a video by public URL. Creates the project/video/source and queues ingest. */
export const POST = route(async ({ userId }, req) => {
  const body = await req.json().catch(() => ({}));
  const url = typeof body?.url === 'string' ? body.url.trim() : '';
  if (!url) return err('A video URL is required');

  const detection = detectProvider(url);
  if (!detection || !detection.permitted) {
    return err(detection?.reason ?? 'This URL cannot be imported', 422, 'unsupported_source');
  }

  const project = await (prisma as any).project.create({
    data: { userId, name: body.title || `Imported ${new Date().toLocaleDateString()}` },
  });

  const video = await (prisma as any).video.create({
    data: {
      projectId: project.id,
      title: body.title || 'Imported video',
      status: 'UPLOADED',
      source: { create: { provider: detection.provider, url, externalId: detection.externalId, kind: detection.kind } },
    },
    include: { source: true },
  });

  const jobId = crypto.randomUUID();
  await (prisma as any).job.create({
    data: { id: jobId, userId, projectId: project.id, videoId: video.id, type: 'ingest-video', status: 'QUEUED', payload: { url } },
  });
  await getQueue().enqueue('ingest-video', { jobId, userId, videoId: video.id, url });

  return json({ video, project, jobId }, { status: 201 });
});
