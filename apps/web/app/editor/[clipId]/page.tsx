import { getServerSession } from 'next-auth/next';
import { redirect } from 'next/navigation';

import { authOptions } from '@/lib/auth';
import { prisma } from '@/lib/db';
import { EditorView } from '@/components/editor/editor-view';

export const dynamic = 'force-dynamic';

export default async function EditorPage({ params }: { params: Promise<{ clipId: string }> }) {
  const { clipId } = await params;
  const session = await getServerSession(authOptions);
  if (!session?.user) redirect('/login');
  const userId = (session.user as { id?: string }).id;

  const clip = await (prisma as any).clip.findFirst({ where: { id: clipId, video: { project: { userId } } } });
  if (!clip) redirect('/dashboard');

  return <EditorView clipId={clipId} />;
}
