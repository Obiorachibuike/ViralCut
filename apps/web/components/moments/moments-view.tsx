'use client';

import { useQuery } from '@tanstack/react-query';
import { motion } from 'framer-motion';
import { Loader2, Play, Sparkles, Wand2 } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Skeleton } from '@/components/ui/skeleton';
import { formatTimestamp } from '@viralcut/shared';
import { useJobStream } from '@/hooks/use-job-stream';

const FILTERS = ['All', 'Funny', 'Emotional', 'Educational', 'Controversial', 'Inspirational', 'Story', 'Business', 'Technical', 'Surprising'];

export function MomentsView({ videoId, initialTitle, initialStatus }: { videoId: string; initialTitle: string; initialStatus: string }) {
  const router = useRouter();
  const [filter, setFilter] = useState('All');
  const [jobId, setJobId] = useState<string | null>(null);
  const { latest } = useJobStream(jobId);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['moments', videoId, jobId],
    queryFn: async () => (await fetch(`/api/videos/${videoId}/moments`)).json(),
    refetchInterval: initialStatus === 'READY' ? false : 3000,
  });

  const moments: any[] = data?.moments ?? [];
  const filtered = filter === 'All' ? moments : moments.filter((m) => (m.categories ?? []).includes(filter) || (m.emotion ?? '').toLowerCase() === filter.toLowerCase());

  async function analyze() {
    const res = await fetch(`/api/videos/${videoId}/analyze`, { method: 'POST' });
    const body = await res.json();
    if (!res.ok) return toast.error(body?.error?.message ?? 'Could not start analysis');
    setJobId(body.jobId);
    toast.success('Analysis started');
  }

  async function generate(momentId: string) {
    const res = await fetch(`/api/moments/${momentId}/generate`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({}) });
    const body = await res.json();
    if (!res.ok) return toast.error(body?.error?.message ?? 'Could not generate clip');
    toast.success('Clip queued');
    router.push(`/editor/${body.clip.id}`);
  }

  async function generateTop(n: number) {
    const top = moments.slice(0, n);
    for (const m of top) {
      await fetch(`/api/moments/${m.id}/generate`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({}) });
    }
    toast.success(`Queued ${top.length} clips`);
    refetch();
  }

  const processing = jobId && latest && latest.type !== 'done' && latest.type !== 'error';

  return (
    <main className="mx-auto max-w-6xl px-6 py-10">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">{initialTitle}</h1>
          <p className="text-sm text-muted-foreground">{moments.length} moments discovered</p>
        </div>
        <div className="flex gap-2">
          {moments.length === 0 && <Button onClick={analyze} disabled={!!processing} className="gap-2">{processing ? <Loader2 className="animate-spin" /> : <Sparkles />} Analyze</Button>}
          {moments.length > 0 && <>
            <Button variant="outline" onClick={() => generateTop(5)}>Generate Top 5</Button>
            <Button variant="outline" onClick={() => generateTop(10)}>Top 10</Button>
          </>}
        </div>
      </div>

      {processing && (
        <Card className="mb-6 p-5">
          <div className="mb-2 flex items-center gap-2 text-sm"><Loader2 className="h-4 w-4 animate-spin text-primary" /> {latest?.message ?? latest?.stage ?? 'Processing…'}</div>
          <Progress value={latest?.progress ?? 0} />
        </Card>
      )}

      <div className="mb-6 flex flex-wrap gap-2">
        {FILTERS.map((f) => (
          <button key={f} onClick={() => setFilter(f)} className={`rounded-full px-3 py-1 text-sm transition-colors ${filter === f ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground hover:text-foreground'}`}>{f}</button>
        ))}
      </div>

      {isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-40" />)}</div>
      ) : filtered.length === 0 ? (
        <Card className="p-12 text-center text-muted-foreground">{moments.length === 0 ? 'No moments yet. Run analysis to discover them.' : 'No moments match this filter.'}</Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((m) => (
            <motion.div key={m.id} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
              <Card className="h-full">
                <CardContent className="p-5">
                  <div className="mb-2 flex items-center justify-between">
                    <Badge variant="accent">{m.viralScore ?? 0}</Badge>
                    <span className="text-xs text-muted-foreground">{formatTimestamp(m.startMs)} – {formatTimestamp(m.endMs)}</span>
                  </div>
                  <h3 className="line-clamp-2 font-medium">{m.title}</h3>
                  {m.description && <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{m.description}</p>}
                  <div className="mt-2 flex flex-wrap gap-1">{(m.categories ?? []).slice(0, 3).map((c: string) => <Badge key={c} variant="outline">{c}</Badge>)}</div>
                  <div className="mt-4 flex gap-2">
                    <Button size="sm" variant="outline" className="flex-1 gap-1"><Play /> Preview</Button>
                    <Button size="sm" className="flex-1 gap-1" onClick={() => generate(m.id)}><Wand2 /> Generate</Button>
                  </div>
                </CardContent>
              </Card>
            </motion.div>
          ))}
        </div>
      )}
    </main>
  );
}
