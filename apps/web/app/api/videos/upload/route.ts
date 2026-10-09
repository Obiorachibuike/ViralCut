import { randomUUID } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';

import { err, json, route } from '@/lib/api';
import { prisma } from '@/lib/db';
import { env } from '@/lib/env';
import { getQueue } from '@/lib/queue';

const ALLOWED = ['video/mp4', 'video/quicktime', 'video/webm', 'video/x-matroska', 'video/x-m4v'];
const MAX_BYTES = 10 * 1024 * 1024 * 1024;

/**
 * Direct upload (single request). For the local storage backend the file is
 * written under STORAGE_LOCAL_DIR so the media engine can read it. Chunked /
 * resumable and R2 presigned uploads are the production path (see README).
 */
export const POST = route(async ({ userId }, req) => {
  const form = await req.formData().catch(() => null);
  const file = form?.get('file');
  if (!(file instanceof File)) return err('A file is required');
  if (!ALLOWED.includes(file.type)) return err(`Unsupported file type: ${file.type}`, 415);
  if (file.size > MAX_BYTES) return err('File exceeds the 10 GB limit', 413);

  const storageKey = `sources/${userId}/${randomUUID()}-${file.name.replace(/[^\w.\-]+/g, '_')}`;

  if ((process.env.STORAGE_BACKEND ?? 'local') !== 'local') {
    return err('Direct upload requires STORAGE_BACKEND=local; use presigned R2 uploads in production.', 501);
  }
  const root = process.env.STORAGE_LOCAL_DIR ?? env.mediaEngineUrl; // local dir
  const abs = join(process.env.STORAGE_LOCAL_DIR ?? '/tmp/viralcut-media', storageKey);
  await mkdir(dirname(abs), { recursive: true });
  await writeFile(abs, Buffer.from(await file.arrayBuffer()));

  const project = await (prisma as any).project.create({ data: { userId, name: file.name } });
  const video = await (prisma as any).video.create({
    data: { projectId: project.id, title: file.name, status: 'UPLOADED', storageKey, mimeType: file.type, sizeBytes: file.size },
  });

  const jobId = randomUUID();
  await (prisma as any).job.create({ data: { id: jobId, userId, projectId: project.id, videoId: video.id, type: 'analyze-video', status: 'QUEUED', payload: { storageKey } } });
  await getQueue().enqueue('analyze-video', { jobId, userId, videoId: video.id, storageKey });

  return json({ video, project, jobId }, { status: 201 });
  void root;
});
