/**
 * Job queue with two drivers.
 *
 *  - `redis` (BullMQ): production. Workers run in a separate process.
 *  - `inline`: development / single-process. Enqueue runs the handler on the
 *    next tick in-process so the full pipeline works without Redis. This is a
 *    real driver over the same handlers — not a fake.
 *
 * The driver is chosen by QUEUE_DRIVER (auto: redis when REDIS_URL is set).
 */
import { QUEUES } from '@viralcut/shared';

import { env } from './env';

export type JobName =
  | 'ingest-video'
  | 'analyze-video'
  | 'generate-clip'
  | 'render-clip'
  | 'generate-broll'
  | 'generate-text-to-video'
  | 'publish-clip'
  | 'cleanup';

export interface JobPayload {
  jobId: string;
  userId: string;
  videoId?: string;
  clipId?: string;
  momentId?: string;
  publicationId?: string;
  projectId?: string;
  url?: string;
  storageKey?: string;
  options?: Record<string, unknown>;
}

export interface QueueDriver {
  readonly name: string;
  enqueue(job: JobName, payload: JobPayload, opts?: { priority?: number }): Promise<void>;
  close(): Promise<void>;
}

class InlineDriver implements QueueDriver {
  readonly name = 'inline';
  private handler: ((job: JobName, payload: JobPayload) => Promise<void>) | null = null;

  setHandler(handler: (job: JobName, payload: JobPayload) => Promise<void>) {
    this.handler = handler;
  }

  async enqueue(job: JobName, payload: JobPayload) {
    // Run off the request path so an HTTP response returns immediately.
    setImmediate(() => {
      void (this.handler ?? fallbackHandler)(job, payload).catch((err) => {
        console.error(`[inline-queue] ${job} failed`, err);
      });
    });
  }

  async close() {}
}

async function fallbackHandler(job: JobName, payload: JobPayload) {
  const { handleJob } = await import('../workers/handlers');
  await handleJob(job, payload);
}

class BullDriver implements QueueDriver {
  readonly name = 'redis';
  private queues = new Map<JobName, import('bullmq').Queue>();

  private async queue(job: JobName) {
    if (!this.queues.has(job)) {
      const { Queue } = await import('bullmq');
      const queueName = isGpuJob(job) ? QUEUES.gpu : QUEUES.cpu;
      this.queues.set(
        job,
        new Queue(queueName, { connection: { url: env.redisUrl }, defaultJobOptions: { attempts: 3, backoff: { type: 'exponential', delay: 2000 }, removeOnComplete: 200, removeOnFail: 200 } }),
      );
    }
    return this.queues.get(job)!;
  }

  async enqueue(job: JobName, payload: JobPayload, opts?: { priority?: number }) {
    const queue = await this.queue(job);
    await queue.add(job, payload, { jobId: payload.jobId, priority: opts?.priority });
  }

  async close() {
    await Promise.all([...this.queues.values()].map((q) => q.close()));
  }
}

export function isGpuJob(job: JobName): boolean {
  return job === 'generate-broll';
}

const globalQueue = globalThis as unknown as { __viralcutQueue?: { driver: QueueDriver; inline: InlineDriver | null } };

function build(): { driver: QueueDriver; inline: InlineDriver | null } {
  if (env.queueDriver === 'redis' && env.redisUrl) {
    return { driver: new BullDriver(), inline: null };
  }
  const inline = new InlineDriver();
  return { driver: inline, inline };
}

export function getQueue(): QueueDriver {
  if (!globalQueue.__viralcutQueue) globalQueue.__viralcutQueue = build();
  return globalQueue.__viralcutQueue.driver;
}

export function getInlineDriver(): InlineDriver | null {
  if (!globalQueue.__viralcutQueue) globalQueue.__viralcutQueue = build();
  return globalQueue.__viralcutQueue.inline;
}
