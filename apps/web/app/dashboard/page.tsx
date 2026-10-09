import { getServerSession } from 'next-auth/next';
import { redirect } from 'next/navigation';
import { Clapperboard, Plus, Video as VideoIcon } from 'lucide-react';
import Link from 'next/link';

import { authOptions } from '@/lib/auth';
import { prisma } from '@/lib/db';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';

export const dynamic = 'force-dynamic';

export default async function DashboardPage() {
  const session = await getServerSession(authOptions);
  if (!session?.user) redirect('/login');
  const userId = (session.user as { id?: string }).id;

  const videos = await (prisma as any).video.findMany({
    where: { project: { userId } },
    orderBy: { createdAt: 'desc' },
    take: 24,
    include: { _count: { select: { moments: true, clips: true } } },
  });

  return (
    <main className="mx-auto max-w-6xl px-6 py-10">
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Your videos</h1>
          <p className="text-sm text-muted-foreground">Welcome back, {session.user.name ?? session.user.email}.</p>
        </div>
        <Button asChild className="gap-2"><Link href="/upload"><Plus /> New video</Link></Button>
      </div>

      {videos.length === 0 ? (
        <Card className="p-12 text-center">
          <VideoIcon className="mx-auto h-10 w-10 text-muted-foreground" />
          <h2 className="mt-4 text-lg font-semibold">No videos yet</h2>
          <p className="mt-1 text-sm text-muted-foreground">Upload a video or import a public URL to find its viral moments.</p>
          <Button asChild className="mt-6"><Link href="/upload">Add your first video</Link></Button>
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {videos.map((v: any) => (
            <Link key={v.id} href={`/video/${v.id}`}>
              <Card className="h-full transition-colors hover:border-primary/40">
                <CardContent className="p-5">
                  <div className="mb-3 flex items-center gap-2">
                    <Clapperboard className="h-4 w-4 text-primary" />
                    <span className="truncate font-medium">{v.title}</span>
                  </div>
                  <div className="flex flex-wrap gap-2 text-xs">
                    <Badge variant="outline">{v.status}</Badge>
                    <Badge variant="secondary">{v._count.moments} moments</Badge>
                    <Badge variant="accent">{v._count.clips} clips</Badge>
                  </div>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </main>
  );
}
