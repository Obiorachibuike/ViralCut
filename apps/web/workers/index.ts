/**
 * Worker entrypoint (BullMQ). Run with `npm run worker`.
 * Consumes CPU and GPU queues and dispatches to `handleJob`.
 */
import { QUEUES } from '@viralcut/shared';
import { Worker } from 'bullmq';

import { env } from '../lib/env';
import { handleJob } from './handlers';
import { type JobName, isGpuJob } from '../lib/queue';

if (!env.redisUrl) {
  console.error('Worker requires REDIS_URL. For single-process dev use the inline queue driver instead.');
  process.exit(1);
}

const connection = { url: env.redisUrl! };

function start(queueName: string, label: string) {
  const worker = new Worker(
    queueName,
    async (job) => handleJob(job.name as JobName, job.data),
    { connection, concurrency: label === 'gpu' ? 1 : 2 },
  );
  worker.on('completed', (job) => console.log(`[${label}] ${job?.name} ${job?.id} completed`));
  worker.on('failed', (job, err) => console.error(`[${label}] ${job?.name} ${job?.id} failed`, err.message));
  return worker;
}

const cpu = start(QUEUES.cpu, 'cpu');
const gpu = start(QUEUES.gpu, 'gpu');
console.log('ViralCut workers started (cpu + gpu)');

async function shutdown() {
  await cpu.close();
  await gpu.close();
  process.exit(0);
}
process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);

export { isGpuJob };
