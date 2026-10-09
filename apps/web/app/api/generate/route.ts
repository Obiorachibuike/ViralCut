import { json, route } from '@/lib/api';
import { prisma } from '@/lib/db';
import { getQueue } from '@/lib/queue';

const ASPECTS = new Set(['9:16', '1:1', '16:9', '4:5']);

/**
 * Kick off text-to-video. Creates the Project + Video shell immediately so the
 * UI has something to navigate to, then a worker fills in the media once the
 * model finishes.
 */
export const POST = route(async ({ userId }, req) => {
  const body = await req.json().catch(() => ({}));
  const prompt = typeof body?.prompt === 'string' ? body.prompt.trim() : '';
  if (!prompt) return json({ error: { message: 'Describe the video you want' } }, { status: 400 });

  const aspectRatio = ASPECTS.has(body?.aspectRatio) ? body.aspectRatio : '9:16';
  const seconds = Math.max(1, Math.min(60, Number(body?.seconds) || 5));

  const project = await (prisma as any).project.create({
    data: { userId, name: prompt.slice(0, 80) },
  });

  const video = await (prisma as any).video.create({
    data: {
      projectId: project.id,
      userId,
      title: prompt.slice(0, 120),
      status: 'PENDING',
      statusMessage: 'Queued for generation',
      metadata: {
        origin: 'TEXT_TO_VIDEO',
        prompt,
        negativePrompt: body?.negativePrompt ?? '',
        aspectRatio,
        seconds,
        seed: body?.seed ?? null,
        provider: body?.provider ?? null,
        model: body?.model ?? null,
      },
      sources: {
        create: {
          kind: 'GENERATED',
          state: 'RESOLVED',
          inputUrl: null,
          provider: body?.provider ?? null,
          providerMeta: { prompt, aspectRatio, seconds },
        },
      },
    },
  });

  const jobId = crypto.randomUUID();
  await (prisma as any).job.create({
    data: {
      id: jobId,
      userId,
      projectId: project.id,
      videoId: video.id,
      type: 'GENERATE_TEXT_TO_VIDEO',
      status: 'QUEUED',
      payload: { prompt, aspectRatio, seconds, negativePrompt: body?.negativePrompt ?? '', provider: body?.provider ?? null, model: body?.model ?? null, seed: body?.seed ?? null },
    },
  });

  await getQueue().enqueue('generate-text-to-video', {
    jobId,
    userId,
    videoId: video.id,
    projectId: project.id,
    options: { prompt, aspectRatio, seconds, negativePrompt: body?.negativePrompt ?? '', provider: body?.provider ?? null, model: body?.model ?? null, seed: body?.seed ?? null },
  });

  return json({ video, project, jobId }, { status: 202 });
});
