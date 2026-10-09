import { getServerSession } from 'next-auth/next';
import { redirect } from 'next/navigation';

import { authOptions } from '@/lib/auth';
import { prisma } from '@/lib/db';
import { MomentsView } from '@/components/moments/moments-view';

export const dynamic = 'force-dynamic';

export default async function VideoPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const session = await getServerSession(authOptions);
  if (!session?.user) redirect('/login');
  const userId = (session.user as { id?: string }).id;

  const video = await (prisma as any).video.findFirst({ where: { id, project: { userId } } });
  if (!video) redirect('/dashboard');

  return <MomentsView videoId={id} initialTitle={video.title} initialStatus={video.status} />;
}
