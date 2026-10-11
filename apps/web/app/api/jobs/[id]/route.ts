import { json, route, HttpError } from '@/lib/api';
import { prisma } from '@/lib/db';

export const GET = route(async ({ userId, params }) => {
  const job = await (prisma as any).job.findFirst({ where: { id: params.id, userId } });
  if (!job) throw new HttpError('Job not found', 404);
  return json({ job });
});
