/**
 * Job handlers (orchestration only — no media work happens here).
 *
 * Each handler delegates heavy work to the FastAPI media engine over HTTP and
 * records progress + results in Postgres, fanning out live events over SSE.
 * Runs in the worker process (BullMQ) or inline (dev driver).
 */
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { prisma } from '../lib/db';
import { eventHub } from '../lib/events';
import { media } from '../lib/media';
import { decryptToken, getPublisher, PublishError } from '../lib/publishing';
import { getQueue, type JobName, type JobPayload } from '../lib/queue';

/** Usage is an append-only event log bucketed by month, not a counter row. */
async function recordUsage(userId: string, metric: string, quantity: number, videoId?: string, clipId?: string) {
  try {
    await (prisma as any).usage.create({
      data: {
        userId,
        metric,
        quantity,
        period: new Date().toISOString().slice(0, 7),
        videoId: videoId ?? null,
        clipId: clipId ?? null,
      },
    });
  } catch (error) {
    // Metering must never fail the job it is measuring.
    console.error('[worker] usage recording failed', error);
  }
}

const POLL_MS = 1500;
const POLL_TIMEOUT_MS = 30 * 60_000;

async function setJobStatus(jobId: string, status: string, extra: Record<string, unknown> = {}) {
  await (prisma as any).job.update({ where: { id: jobId }, data: { status, ...extra } });
  await eventHub.publish({ type: 'stage', jobId, message: status, stage: status, at: Date.now() });
}

async function fail(jobId: string, error: unknown) {
  const message = error instanceof Error ? error.message : String(error);
  console.error(`[worker] job ${jobId} failed`, error);
  try {
    await (prisma as any).job.update({
      where: { id: jobId },
      data: { status: 'FAILED', completedAt: new Date(), error: { message } },
    });
  } catch {
    /* job may not exist */
  }
  await eventHub.publish({ type: 'error', jobId, message, at: Date.now() });
}

export async function handleJob(job: JobName, payload: JobPayload) {
  try {
    switch (job) {
      case 'ingest-video':
        return await ingestVideo(payload);
      case 'analyze-video':
        return await analyzeVideo(payload);
      case 'generate-clip':
        return await generateClip(payload);
      case 'render-clip':
        return await renderClip(payload);
      case 'generate-text-to-video':
        return await generateTextToVideo(payload);
      case 'publish-clip':
        return await publishClip(payload);
      case 'cleanup':
        return await cleanup(payload);
      default:
        throw new Error(`unhandled job: ${job}`);
    }
  } catch (error) {
    await fail(payload.jobId, error);
    throw error;
  }
}

async function ingestVideo(payload: JobPayload) {
  const { videoId, userId } = payload;
  const video = await (prisma as any).video.findUnique({ where: { id: videoId }, include: { source: true } });
  if (!video) throw new Error('Video not found');

  let storageKey: string | null = video.storageKey;

  if (video.source?.url) {
    await setJobStatus(payload.jobId, 'PROCESSING');
    await (prisma as any).video.update({ where: { id: videoId }, data: { status: 'PREPARING' } });
    const downloaded = await media.download(video.source.url, payload.jobId);
    storageKey = downloaded.storageKey;
    await (prisma as any).video.update({
      where: { id: videoId },
      data: { storageKey, title: video.title || downloaded.provider },
    });
    await (prisma as any).videoSource.update({ where: { id: video.source.id }, data: { status: 'DOWNLOADED' } });
  }

  if (!storageKey) throw new Error('No media to analyze: upload a file or import a permitted URL.');

  await setJobStatus(payload.jobId, 'COMPLETED', { completedAt: new Date() });
  await getQueue().enqueue('analyze-video', { jobId: payload.jobId, userId, videoId, storageKey, options: payload.options });
}

async function analyzeVideo(payload: JobPayload) {
  const { videoId, storageKey, userId } = payload;
  await setJobStatus(payload.jobId, 'TRANSCRIBING');
  await (prisma as any).video.update({ where: { id: videoId }, data: { status: 'PREPARING' } });

  const run = await media.process({ runId: payload.jobId, storageKey, options: (payload.options ?? {}), skipDiarization: false });
  const result = await pollRun(run.runId, payload.jobId);

  const mediaInfo = (result.media ?? {}) as Record<string, any>;
  await (prisma as any).video.update({
    where: { id: videoId },
    data: {
      status: 'READY',
      durationMs: mediaInfo.durationMs ?? undefined,
      width: mediaInfo.width ?? undefined,
      height: mediaInfo.height ?? undefined,
      sizeBytes: mediaInfo.sizeBytes ?? undefined,
      mimeType: mediaInfo.mimeType ?? undefined,
    },
  });

  for (const sp of (result.speakers ?? []) as any[]) {
    await (prisma as any).speaker.create({
      data: { videoId, label: sp.label, totalMs: sp.totalMs ?? 0, segmentCount: sp.segmentCount ?? 0, color: sp.color ?? null },
    });
  }

  const moments = (result.moments ?? []) as any[];
  for (let i = 0; i < moments.length; i += 1) {
    const m = moments[i];
    await (prisma as any).moment.create({
      data: {
        videoId,
        title: m.title ?? `Moment ${i + 1}`,
        description: m.description ?? null,
        startMs: m.startMs,
        endMs: m.endMs,
        hook: m.hook ?? null,
        viralScore: m.viralScore ?? 0,
        confidence: m.confidence ?? 0,
        emotion: m.emotion ?? null,
        categories: m.categories ?? [],
        tags: m.tags ?? [],
        rank: i + 1,
        scores: m.scores ?? {},
        boundary: m.boundary ?? {},
        thumbnailKey: m.thumbnailKey ?? null,
        transcriptPreview: m.transcriptPreview ?? null,
      },
    });
  }

  await setJobStatus(payload.jobId, 'COMPLETED', { completedAt: new Date() });
  await eventHub.publish({ type: 'done', jobId: payload.jobId, message: 'Analysis complete', payload: { videoId, momentCount: moments.length }, at: Date.now() });
  void userId;
}

async function pollRun(runId: string, jobId: string): Promise<Record<string, any>> {
  const started = Date.now();
  let lastProgress = -1;
  while (Date.now() - started < POLL_TIMEOUT_MS) {
    const state = await media.run(runId);
    if (state.progress !== lastProgress) {
      lastProgress = state.progress;
      await eventHub.publish({ type: 'progress', jobId, progress: state.progress, stage: state.state, message: state.events.at(-1)?.message, at: Date.now() });
    }
    if (state.state === 'COMPLETED' && state.result) return state.result;
    if (state.state === 'FAILED') throw new Error(state.error ?? 'Processing failed');
    await new Promise((r) => setTimeout(r, POLL_MS));
  }
  throw new Error('Processing timed out');
}

async function generateClip(payload: JobPayload) {
  const { clipId, momentId } = payload;
  const moment = await (prisma as any).moment.findUnique({ where: { id: momentId } });
  if (!moment) throw new Error('Moment not found');
  const clip = await (prisma as any).clip.create({
    data: {
      videoId: moment.videoId,
      momentId,
      title: moment.title,
      startMs: moment.startMs,
      endMs: moment.endMs,
      aspectRatio: '9:16',
      status: 'READY',
      viralScore: moment.viralScore,
      categories: moment.categories ?? [],
      hook: moment.hook ?? null,
      scores: moment.scores ?? {},
    },
  });
  await setJobStatus(payload.jobId, 'COMPLETED', { completedAt: new Date() });
  await eventHub.publish({ type: 'done', jobId: payload.jobId, payload: { clipId: clip.id }, at: Date.now() });
  void clipId;
}

async function renderClip(payload: JobPayload) {
  const { clipId } = payload;
  await setJobStatus(payload.jobId, 'RENDERING');
  const clip = await (prisma as any).clip.findUnique({ where: { id: clipId }, include: { moment: { include: { video: true } } } });
  if (!clip?.moment?.video) throw new Error('Clip not found');

  const video = clip.moment.video;
  const options = (payload.options ?? {}) as Record<string, any>;
  const renderOptions = clip.renderOptions ?? {};

  const out = await media.render({
    storageKey: video.storageKey,
    outputKey: clip.storageKey ?? `clips/${clip.videoId}/${clipId}.mp4`,
    startMs: clip.startMs,
    endMs: clip.endMs,
    srcWidth: video.width ?? 1920,
    srcHeight: video.height ?? 1080,
    aspect: clip.aspectRatio ?? '9:16',
    reframeMode: options.reframeMode ?? renderOptions.reframeMode ?? 'AUTO',
    captionStyle: options.captionStyle ?? renderOptions.captionStyle ?? 'CREATOR',
    captions: renderOptions.captions ?? [],
    hookText: renderOptions.hookText ?? null,
    watermarkText: renderOptions.watermarkText ?? null,
    muteAudio: renderOptions.muteAudio ?? false,
    volume: renderOptions.volume ?? 1,
    maxShortSide: renderOptions.maxShortSide ?? 1080,
    preset: renderOptions.preset ?? 'veryfast',
    crf: renderOptions.crf ?? 23,
  });

  await (prisma as any).clip.update({
    where: { id: clipId },
    data: { storageKey: (out as any).storageKey, status: 'READY', file: (out as any).storageKey, renderOptions },
  });

  await recordUsage(payload.userId, 'CLIP_RENDERED', 1, clip.videoId, clipId);

  await setJobStatus(payload.jobId, 'COMPLETED', { completedAt: new Date() });
  await eventHub.publish({ type: 'done', jobId: payload.jobId, payload: { clipId }, at: Date.now() });
}

/**
 * Text-to-video: ask the engine to generate, then attach the result to the
 * Video row so it flows through the ordinary analyze -> moments -> clips path.
 */
async function generateTextToVideo(payload: JobPayload) {
  const { videoId } = payload;
  const options = (payload.options ?? {}) as Record<string, any>;
  await setJobStatus(payload.jobId, 'GENERATING');
  await (prisma as any).video.update({
    where: { id: videoId },
    data: { status: 'PREPARING', statusMessage: 'Generating video from your prompt' },
  });

  const run = await media.generateTextToVideo({
    runId: payload.jobId,
    prompt: options.prompt,
    negativePrompt: options.negativePrompt ?? '',
    seconds: options.seconds ?? 5,
    aspectRatio: options.aspectRatio ?? '9:16',
    seed: options.seed ?? null,
    provider: options.provider ?? null,
    model: options.model ?? null,
  });

  const result = await pollRun(run.runId, payload.jobId);

  await (prisma as any).video.update({
    where: { id: videoId },
    data: {
      status: 'READY',
      statusMessage: 'Generated',
      storageKey: result.storageKey,
      thumbnailKey: result.thumbnailKey ?? null,
      durationMs: result.durationMs ?? undefined,
      width: result.width ?? undefined,
      height: result.height ?? undefined,
      fps: result.fps ?? undefined,
      sizeBytes: result.sizeBytes ?? undefined,
      metadata: {
        origin: 'TEXT_TO_VIDEO',
        prompt: options.prompt,
        provider: result.provider,
        model: result.model,
        providerJobId: result.providerJobId ?? null,
      },
    },
  });
  await (prisma as any).videoSource.updateMany({
    where: { videoId, kind: 'GENERATED' },
    data: { state: 'DOWNLOADED', storageKey: result.storageKey, sizeBytes: result.sizeBytes ?? undefined },
  });

  await recordUsage(
    payload.userId,
    'VIDEO_GENERATED',
    Math.max(1, Math.round((result.durationMs ?? 0) / 1000)),
    videoId,
  );

  await setJobStatus(payload.jobId, 'COMPLETED', { completedAt: new Date() });
  await eventHub.publish({
    type: 'done',
    jobId: payload.jobId,
    message: 'Video generated',
    payload: { videoId, storageKey: result.storageKey },
    at: Date.now(),
  });

  // Generated footage is source material: analyse it unless the caller opted out.
  if (options.autoAnalyze !== false) {
    await getQueue().enqueue('analyze-video', {
      jobId: payload.jobId,
      userId: payload.userId,
      videoId,
      storageKey: result.storageKey,
    });
  }
}

/**
 * Publish a rendered clip to one connected account.
 *
 * The clip lives in the media engine's storage, so we ask the engine for a
 * short-lived URL and stream it to a temp file — the worker never holds storage
 * credentials, and platforms that pull server-side can use the URL directly.
 */
async function publishClip(payload: JobPayload) {
  const { publicationId } = payload;
  const publication = await (prisma as any).publication.findUnique({
    where: { id: publicationId },
    include: { account: true, clip: true },
  });
  if (!publication) throw new Error('Publication not found');
  if (publication.userId !== payload.userId) throw new Error('Not authorised for this publication');

  const { account, clip } = publication;
  const publisher = getPublisher(account.platform);

  await (prisma as any).publication.update({ where: { id: publicationId }, data: { status: 'UPLOADING' } });
  await setJobStatus(payload.jobId, 'UPLOADING');

  let token = {
    accessToken: decryptToken(account.accessToken),
    refreshToken: account.refreshToken ? decryptToken(account.refreshToken) : null,
    expiresAt: account.expiresAt,
    tokenType: account.tokenType ?? undefined,
  };

  // Refresh proactively rather than failing mid-upload.
  if (publisher.refresh && account.refreshToken && (!account.expiresAt || account.expiresAt < new Date())) {
    const next = await publisher.refresh(token);
    token = { ...token, ...next };
    await (prisma as any).socialAccount.update({
      where: { id: account.id },
      data: {
        accessToken: (await import('../lib/publishing/crypto')).encryptToken(next.accessToken),
        refreshToken: next.refreshToken
          ? (await import('../lib/publishing/crypto')).encryptToken(next.refreshToken)
          : account.refreshToken,
        expiresAt: next.expiresAt ?? null,
      },
    });
  }

  const signed = await media.storageUrl(clip.storageKey);
  const dir = await mkdtemp(join(tmpdir(), 'viralcut-publish-'));
  try {
    const res = await fetch(signed.url);
    if (!res.ok) throw new PublishError('Could not fetch the rendered clip from storage.', { code: 'storage_fetch' });
    const filePath = join(dir, 'clip.mp4');
    await writeFile(filePath, Buffer.from(await res.arrayBuffer()));

    const outcome = await publisher.publish(
      token,
      {
        title: publication.title,
        description: publication.description,
        tags: publication.tags ?? [],
        privacy: publication.privacy,
        options: {
          ...(publication.options ?? {}),
          // Adapters need the platform-side id the account was connected as.
          pageId: account.platformUserId,
          personId: account.platformUserId,
          ownerUrn: `urn:li:person:${account.platformUserId}`,
        },
      },
      { filePath, fileUrl: signed.url, mimeType: 'video/mp4', sizeBytes: signed.sizeBytes },
    );

    await (prisma as any).publication.update({
      where: { id: publicationId },
      data: {
        status: outcome.status === 'PUBLISHED' ? 'PUBLISHED' : 'PROCESSING',
        platformPostId: outcome.platformPostId,
        platformUrl: outcome.platformUrl ?? null,
        publishedAt: outcome.status === 'PUBLISHED' ? new Date() : null,
        error: null,
      },
    });
    await (prisma as any).socialAccount.update({ where: { id: account.id }, data: { lastUsedAt: new Date(), lastError: null } });
    await recordUsage(payload.userId, 'CLIP_PUBLISHED', 1, clip.videoId, clip.id);

    await setJobStatus(payload.jobId, 'COMPLETED', { completedAt: new Date() });
    await eventHub.publish({
      type: 'done',
      jobId: payload.jobId,
      message: `Published to ${publisher.label}`,
      payload: { publicationId, platformPostId: outcome.platformPostId, platformUrl: outcome.platformUrl ?? null },
      at: Date.now(),
    });
  } catch (error) {
    const message = error instanceof PublishError ? error.message : 'Publishing failed';
    const code = error instanceof PublishError ? error.opts.code : undefined;
    if (error instanceof PublishError && error.opts.logDetail) {
      console.error(`[publish] ${publicationId} failed`, error.opts.logDetail);
    }
    await (prisma as any).publication.update({
      where: { id: publicationId },
      data: { status: 'FAILED', error: message, attempts: { increment: 1 } },
    });
    // A dead token should not keep being retried — flag the account.
    if (code === 'token_invalid') {
      await (prisma as any).socialAccount.update({
        where: { id: account.id },
        data: { status: 'EXPIRED', lastError: message },
      });
    } else {
      await (prisma as any).socialAccount.update({ where: { id: account.id }, data: { lastError: message } });
    }
    await setJobStatus(payload.jobId, 'FAILED', { completedAt: new Date() });
    await eventHub.publish({ type: 'error', jobId: payload.jobId, message, at: Date.now() });
    throw error;
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

async function cleanup(payload: JobPayload) {
  await setJobStatus(payload.jobId, 'COMPLETED', { completedAt: new Date() });
}
