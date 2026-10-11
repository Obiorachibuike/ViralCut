import { getServerSession } from 'next-auth/next';

import { authOptions } from '@/lib/auth';
import { prisma } from '@/lib/db';
import { eventHub } from '@/lib/events';

export const dynamic = 'force-dynamic';

/**
 * Server-Sent Events for live job progress (no 1s polling). Ownership-checked.
 */
export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const session = await getServerSession(authOptions);
  const userId = (session?.user as { id?: string } | undefined)?.id;
  if (!userId) return new Response('Unauthorized', { status: 401 });

  const job = await (prisma as any).job.findFirst({ where: { id, userId } });
  if (!job) return new Response('Not found', { status: 404 });

  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    start(controller) {
      const send = (event: unknown) => controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
      send({ type: 'stage', stage: job.status, at: Date.now() });
      const unsub = eventHub.subscribe(id, (event) => send(event));
      const ping = setInterval(() => controller.enqueue(encoder.encode(': ping\n\n')), 25_000);
      _req.signal.addEventListener('abort', () => {
        clearInterval(ping);
        unsub();
        controller.close();
      });
    },
  });

  return new Response(stream, {
    headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache, no-transform', Connection: 'keep-alive' },
  });
}
