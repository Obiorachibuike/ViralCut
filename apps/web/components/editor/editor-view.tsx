'use client';

import { useQuery } from '@tanstack/react-query';
import { Loader2, Wand2 } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { ASPECT_RATIOS, CAPTION_STYLES, REFRAME_MODES } from '@viralcut/shared';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Progress } from '@/components/ui/progress';
import { PublishPanel } from '@/components/editor/publish-panel';
import { useJobStream } from '@/hooks/use-job-stream';

export function EditorView({ clipId }: { clipId: string }) {
  const { data } = useQuery({ queryKey: ['clip', clipId], queryFn: async () => (await fetch(`/api/clips/${clipId}`)).json() });
  const clip = data?.clip;
  const [jobId, setJobId] = useState<string | null>(null);
  const { latest } = useJobStream(jobId);
  const [aspect, setAspect] = useState<string>(clip?.aspectRatio ?? '9:16');
  const [style, setStyle] = useState<string>(clip?.captionStyle ?? 'CREATOR');
  const [reframe, setReframe] = useState<string>('AUTO');
  const [hook, setHook] = useState<string>(clip?.hook ?? '');

  async function save() {
    await fetch(`/api/clips/${clipId}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ aspectRatio: aspect, captionStyle: style, hook, renderOptions: { reframeMode: reframe, captionStyle: style, hookText: hook } }) });
    toast.success('Saved');
  }

  async function render() {
    await save();
    const res = await fetch(`/api/clips/${clipId}/render`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ reframeMode: reframe, captionStyle: style }) });
    const body = await res.json();
    if (!res.ok) return toast.error(body?.error?.message ?? 'Render failed');
    setJobId(body.jobId);
    toast.success('Rendering');
  }

  if (!clip) return <div className="p-10 text-muted-foreground">Loading…</div>;

  return (
    <main className="mx-auto grid max-w-6xl gap-6 px-6 py-10 lg:grid-cols-[1fr_360px]">
      <div>
        <h1 className="mb-4 text-2xl font-bold">{clip.title}</h1>
        <Card className="overflow-hidden">
          <div className="flex aspect-video items-center justify-center bg-black">
            {clip.storageKey ? (
              <video src={`/api/media/${encodeURIComponent(clip.storageKey)}`} controls className="max-h-full" />
            ) : (
              <span className="text-sm text-muted-foreground">Render to preview</span>
            )}
          </div>
        </Card>
        {jobId && latest && latest.type !== 'done' && latest.type !== 'error' && (
          <Card className="mt-4 p-5">
            <div className="mb-2 flex items-center gap-2 text-sm"><Loader2 className="h-4 w-4 animate-spin text-primary" /> {latest?.message ?? 'Rendering…'}</div>
            <Progress value={latest?.progress ?? 0} />
          </Card>
        )}
      </div>

      <div className="space-y-4">
        <Card>
          <CardHeader><CardTitle>Hook</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            <Input value={hook} onChange={(e) => setHook(e.target.value)} placeholder="Opening hook line" />
            <Button variant="outline" size="sm" className="gap-1"><Wand2 /> Regenerate hooks</Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Format</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <div>
              <Label className="mb-2 block">Aspect ratio</Label>
              <div className="flex flex-wrap gap-2">
                {Object.values(ASPECT_RATIOS).map((r) => (
                  <button key={r.id} onClick={() => setAspect(r.id)} className={`rounded-md px-3 py-1.5 text-sm ${aspect === r.id ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground'}`}>{r.label}</button>
                ))}
              </div>
            </div>
            <div>
              <Label className="mb-2 block">Caption style</Label>
              <div className="flex flex-wrap gap-2">
                {CAPTION_STYLES.map((s) => (
                  <button key={s} onClick={() => setStyle(s)} className={`rounded-md px-3 py-1.5 text-sm ${style === s ? 'bg-secondary text-secondary-foreground' : 'bg-muted text-muted-foreground'}`}>{s.replace('_', ' ').toLowerCase()}</button>
                ))}
              </div>
            </div>
            <div>
              <Label className="mb-2 block">Reframing</Label>
              <div className="flex flex-wrap gap-2">
                {REFRAME_MODES.map((m) => (
                  <button key={m} onClick={() => setReframe(m)} className={`rounded-md px-3 py-1.5 text-sm ${reframe === m ? 'bg-accent text-accent-foreground' : 'bg-muted text-muted-foreground'}`}>{m.replace('_', ' ').toLowerCase()}</button>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>

        <div className="flex items-center justify-between">
          <Badge variant="accent">Score {clip.viralScore ?? 0}</Badge>
          <div className="flex gap-2">
            <Button variant="outline" onClick={save}>Save</Button>
            <Button onClick={render} disabled={!!jobId && latest?.type !== 'done' && latest?.type !== 'error'}>Export clip</Button>
          </div>
        </div>

        {clip.storageKey && <PublishPanel clipId={clipId} defaultTitle={clip.title ?? ''} />}
      </div>
    </main>
  );
}
