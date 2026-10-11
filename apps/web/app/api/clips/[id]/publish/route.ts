import { json, route, HttpError } from '@/lib/api';
import { prisma } from '@/lib/db';
import { isPlatform } from '@/lib/publishing';
import { getQueue } from '@/lib/queue';

const PRIVACY = new Set(['PUBLIC', 'UNLISTED', 'PRIVATE']);

/** Queue a clip for publishing to one connected account. */
export const POST = route(async ({ userId, params }, req) => {
  const clip = await (prisma as any).clip.findFirst({
    where: { id: params.id, video: { project: { userId } } },
  });
  if (!clip) throw new HttpError('Clip not found', 404);
  if (!clip.storageKey) throw new HttpError('Render the clip before publishing it', 409, 'not_rendered');

  const body = await req.json().catch(() => ({}));
  const accountId = typeof body?.accountId === 'string' ? body.accountId : '';
  if (!accountId) throw new HttpError('Choose an account to publish to', 400);

  const account = await (prisma as any).socialAccount.findFirst({ where: { id: accountId, userId } });
  if (!account) throw new HttpError('Account not found', 404);
  if (account.status !== 'CONNECTED') {
    throw new HttpError('That account is no longer connected. Reconnect it and try again.', 409, 'account_expired');
  }
  if (!isPlatform(account.platform)) throw new HttpError('Unsupported platform', 400);

  const privacy = PRIVACY.has(body?.privacy) ? body.privacy : 'PUBLIC';
  const title = typeof body?.title === 'string' && body.title.trim() ? body.title.trim() : clip.title;

  const publication = await (prisma as any).publication.create({
    data: {
      clipId: clip.id,
      userId,
      accountId: account.id,
      platform: account.platform,
      title,
      description: typeof body?.description === 'string' ? body.description : null,
      tags: Array.isArray(body?.tags) ? body.tags.filter((t: unknown) => typeof t === 'string') : [],
      privacy,
      options: body?.options ?? {},
      status: body?.scheduledFor ? 'SCHEDULED' : 'QUEUED',
      scheduledFor: body?.scheduledFor ? new Date(body.scheduledFor) : null,
    },
  });

  const jobId = crypto.randomUUID();
  await (prisma as any).job.create({
    data: {
      id: jobId,
      userId,
      videoId: clip.videoId,
      type: 'PUBLISH_CLIP',
      status: 'QUEUED',
      payload: { publicationId: publication.id, clipId: clip.id },
    },
  });
  await getQueue().enqueue('publish-clip', {
    jobId,
    userId,
    videoId: clip.videoId,
    clipId: clip.id,
    publicationId: publication.id,
  });

  return json({ publication, jobId }, { status: 202 });
});
