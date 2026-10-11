import { json, route, HttpError } from '@/lib/api';
import { prisma } from '@/lib/db';

async function owned(userId: string, id: string) {
  const clip = await (prisma as any).clip.findFirst({ where: { id, video: { project: { userId } } }, include: { moment: true, video: true } });
  if (!clip) throw new HttpError('Clip not found', 404);
  return clip;
}

export const GET = route(async ({ userId, params }) => json({ clip: await owned(userId, params.id) }));

export const PATCH = route(async ({ userId, params }, req) => {
  await owned(userId, params.id);
  const body = await req.json().catch(() => ({}));
  const data: Record<string, unknown> = {};
  if (body.title !== undefined) data.title = body.title;
  if (body.aspectRatio !== undefined) data.aspectRatio = body.aspectRatio;
  if (body.captionStyle !== undefined) data.captionStyle = body.captionStyle;
  if (body.startMs !== undefined) data.startMs = body.startMs;
  if (body.endMs !== undefined) data.endMs = body.endMs;
  if (body.hook !== undefined) data.hook = body.hook;
  if (body.renderOptions !== undefined) data.renderOptions = body.renderOptions;
  const clip = await (prisma as any).clip.update({ where: { id: params.id }, data });
  return json({ clip });
});

export const DELETE = route(async ({ userId, params }) => {
  await owned(userId, params.id);
  await (prisma as any).clip.delete({ where: { id: params.id } });
  return json({ deleted: true });
});
