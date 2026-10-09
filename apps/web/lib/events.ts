/**
 * Live-update hub. Browsers subscribe to `/api/jobs/[id]/stream` (SSE).
 * Producers call `publish(jobId, event)`.
 *
 * Backends: Redis pub/sub when REDIS_URL is set (multi-process), otherwise an
 * in-process emitter (single-process dev). Producers never block on a push.
 */
import type { Redis } from 'ioredis';

import { env } from './env';

export interface JobEvent {
  type: 'stage' | 'progress' | 'done' | 'error' | 'moment';
  jobId: string;
  stage?: string;
  progress?: number;
  message?: string;
  payload?: unknown;
  at: number;
}

type Listener = (event: JobEvent) => void;

class InMemoryHub {
  private listeners = new Map<string, Set<Listener>>();
  subscribe(jobId: string, listener: Listener): () => void {
    let set = this.listeners.get(jobId);
    if (!set) {
      set = new Set();
      this.listeners.set(jobId, set);
    }
    set.add(listener);
    return () => {
      set.delete(listener);
      if (set.size === 0) this.listeners.delete(jobId);
    };
  }
  publish(event: JobEvent) {
    const set = this.listeners.get(event.jobId);
    if (set) for (const l of set) l(event);
  }
}

export class EventHub {
  private memory = new InMemoryHub();
  private redisPub: Redis | null = null;
  private redisSub: Redis | null = null;

  private async ensureRedis() {
    if (!env.redisUrl) return;
    if (this.redisPub) return;
    const { default: RedisCtor } = await import('ioredis');
    this.redisPub = new RedisCtor(env.redisUrl);
    this.redisSub = new RedisCtor(env.redisUrl);
    this.redisSub.psubscribe('viralcut:job:*');
    this.redisSub.on('pmessage', (_pattern, channel, message) => {
      const jobId = channel.split(':').pop() as string;
      try {
        const event = JSON.parse(message) as JobEvent;
        this.memory.publish({ ...event, jobId });
      } catch {
        /* ignore malformed */
      }
    });
  }

  async publish(event: JobEvent) {
    if (env.redisUrl) {
      await this.ensureRedis();
      if (this.redisPub) {
        void this.redisPub.publish(`viralcut:job:${event.jobId}`, JSON.stringify(event));
        return;
      }
    }
    this.memory.publish(event);
  }

  subscribe(jobId: string, listener: Listener): () => void {
    // For Redis, pmessage re-publishes into the in-memory hub, so subscribing to
    // memory is sufficient on both backends.
    if (env.redisUrl) void this.ensureRedis();
    return this.memory.subscribe(jobId, listener);
  }
}

const globalHub = globalThis as unknown as { __viralcutHub?: EventHub };
export const eventHub: EventHub = globalHub.__viralcutHub ?? (globalHub.__viralcutHub = new EventHub());
