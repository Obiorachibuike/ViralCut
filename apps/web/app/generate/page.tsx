'use client';

import { useQuery } from '@tanstack/react-query';
import { motion } from 'framer-motion';
import { AlertTriangle, Loader2, Sparkles, Wand2 } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { toast } from 'sonner';

import { ASPECT_RATIOS } from '@viralcut/shared';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Progress } from '@/components/ui/progress';
import { useJobStream } from '@/hooks/use-job-stream';

interface Providers {
  active: string | null;
  activeConfigured: boolean;
  maxSeconds: number;
  providers: { name: string; label: string; configured: boolean; reason?: string }[];
  error?: string;
}

export default function GeneratePage() {
  const router = useRouter();
  const [prompt, setPrompt] = useState('');
  const [negative, setNegative] = useState('');
  const [aspect, setAspect] = useState('9:16');
  const [seconds, setSeconds] = useState(5);
  const [jobId, setJobId] = useState<string | null>(null);
  const [videoId, setVideoId] = useState<string | null>(null);
  const { latest } = useJobStream(jobId);

  const { data: providers } = useQuery({
    queryKey: ['t2v-providers'],
    queryFn: async () => (await fetch('/api/generate/providers')).json() as Promise<Providers>,
  });

  const ready = providers?.activeConfigured === true;
  const running = Boolean(jobId) && latest?.type !== 'done' && latest?.type !== 'error';
  const done = latest?.type === 'done';
  const failed = latest?.type === 'error';

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const res = await fetch('/api/generate', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ prompt, negativePrompt: negative, aspectRatio: aspect, seconds }),
    });
    const body = await res.json();
    if (!res.ok) {
      toast.error(body?.error?.message ?? 'Could not start generation');
      return;
    }
    setJobId(body.jobId);
    setVideoId(body.video.id);
    toast.success('Generation queued');
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-10">
      <h1 className="text-2xl font-bold">Text to video</h1>
      <p className="mb-6 text-sm text-muted-foreground">
        Describe a shot and ViralCut generates it, then runs the usual moment discovery and clipping
        on the result.
      </p>

      {providers && !ready && (
        <Card className="mb-6 border-amber-500/30 bg-amber-500/5">
          <CardContent className="flex gap-3 p-5">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-400" />
            <div className="text-sm">
              <p className="font-medium">No text-to-video backend is active on this instance.</p>
              <p className="mt-1 text-muted-foreground">
                {providers.error ?? 'Set VIRALCUT_T2V_PROVIDER and the matching API key to enable generation.'}
              </p>
              <ul className="mt-3 space-y-1 text-muted-foreground">
                {providers.providers.map((p) => (
                  <li key={p.name} className="flex items-center gap-2">
                    <span className={p.configured ? 'text-accent' : 'text-muted-foreground'}>
                      {p.configured ? '●' : '○'}
                    </span>
                    {p.label}
                    {p.reason ? <span className="text-xs opacity-70">— {p.reason}</span> : null}
                  </li>
                ))}
              </ul>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Describe the video</CardTitle>
          <CardDescription>Be specific about subject, action, lens and mood.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="prompt">Prompt</Label>
              <textarea
                id="prompt"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                required
                rows={3}
                placeholder="A golden retriever surfing a turquoise wave at sunrise, slow motion, 35mm"
                className="flex w-full rounded-md border border-input bg-surface px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="negative">Avoid (optional)</Label>
              <Input
                id="negative"
                value={negative}
                onChange={(e) => setNegative(e.target.value)}
                placeholder="text, watermark, distorted faces"
              />
            </div>

            <div>
              <Label className="mb-2 block">Aspect ratio</Label>
              <div className="flex flex-wrap gap-2">
                {Object.values(ASPECT_RATIOS).map((r) => (
                  <button
                    key={r.id}
                    type="button"
                    onClick={() => setAspect(r.id)}
                    className={`rounded-md px-3 py-1.5 text-sm ${
                      aspect === r.id ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground'
                    }`}
                  >
                    {r.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="seconds">Duration: {seconds}s</Label>
              <input
                id="seconds"
                type="range"
                min={1}
                max={Math.min(12, providers?.maxSeconds ?? 10)}
                value={seconds}
                onChange={(e) => setSeconds(Number(e.target.value))}
                className="w-full accent-[hsl(var(--primary))]"
              />
            </div>

            <Button type="submit" disabled={!prompt || running || !ready} className="gap-2">
              {running ? <Loader2 className="animate-spin" /> : <Wand2 />} Generate video
            </Button>
          </form>
        </CardContent>
      </Card>

      {jobId && (
        <Card className="mt-6 p-5">
          {running && (
            <>
              <div className="mb-2 flex items-center gap-2 text-sm">
                <Loader2 className="h-4 w-4 animate-spin text-primary" />
                {latest?.message ?? latest?.stage ?? 'Generating…'}
              </div>
              <Progress value={latest?.progress ?? 0} />
            </>
          )}
          {done && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
              <div className="flex items-center gap-2 text-sm text-accent">
                <Sparkles className="h-4 w-4" /> Video generated
              </div>
              {videoId && (
                <Button asChild className="mt-4" onClick={() => router.refresh()}>
                  <Link href={`/video/${videoId}`}>Open the video and find its moments</Link>
                </Button>
              )}
            </motion.div>
          )}
          {failed && (
            <div className="flex items-center gap-2 text-sm text-destructive">
              <AlertTriangle className="h-4 w-4" /> {latest?.message ?? 'Generation failed'}
            </div>
          )}
        </Card>
      )}

      {ready && (
        <p className="mt-4 flex items-center gap-2 text-xs text-muted-foreground">
          <Badge variant="outline">{providers?.active}</Badge>
          {`Up to ${providers?.maxSeconds ?? 10}s per generation`}
        </p>
      )}
    </main>
  );
}
