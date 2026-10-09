import { NextResponse } from 'next/server';

import { prisma } from '@/lib/db';
import { eventHub } from '@/lib/events';

/**
 * Receives stage/done callbacks from the FastAPI media engine and fans them out
 * over SSE. Guarded by a shared token (never exposed to the browser).
 */
export async function POST(request: Request) {
  const token = request.headers.get('x-viralcut-callback-token');
  if (!token || token !== process.env.VIRALCUT_CALLBACK_TOKEN) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const body = await request.json().catch(() => ({}));
  const jobId = body?.runId ?? body?.jobId;
  if (!jobId) return NextResponse.json({ ok: true });

  if (body?.type === 'done') {
    await (prisma as any).job.update({ where: { id: jobId }, data: { status: 'COMPLETED', completedAt: new Date(), result: body.result ?? {} } }).catch(() => {});
    await eventHub.publish({ type: 'done', jobId, message: 'Complete', at: Date.now() });
  } else {
    await eventHub.publish({
      type: 'progress',
      jobId,
      progress: body?.progress,
      stage: body?.stage,
      message: body?.message,
      at: Date.now(),
    });
  }

  return NextResponse.json({ ok: true });
}
