'use client';

import { Check, Link2, Loader2, Upload, X } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useRef, useState } from 'react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Progress } from '@/components/ui/progress';

export default function UploadPage() {
  const router = useRouter();
  const fileRef = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const [url, setUrl] = useState('');
  const [busy, setBusy] = useState<'upload' | 'url' | null>(null);
  const [progress, setProgress] = useState(0);
  const [resolve, setResolve] = useState<any>(null);

  async function uploadFile(file: File) {
    setBusy('upload');
    setProgress(5);
    try {
      const form = new FormData();
      form.append('file', file);
      const xhr = new XMLHttpRequest();
      const res = await new Promise<any>((res2, rej) => {
        xhr.upload.onprogress = (e) => e.lengthComputable && setProgress(Math.round((e.loaded / e.total) * 100));
        xhr.onload = () => res2({ status: xhr.status, body: JSON.parse(xhr.responseText || '{}') });
        xhr.onerror = () => rej(new Error('Upload failed'));
        xhr.open('POST', '/api/videos/upload');
        xhr.send(form);
      });
      if (res.status >= 400) throw new Error(res.body?.error?.message ?? 'Upload failed');
      toast.success('Upload complete — analyzing');
      router.push(`/video/${res.body.video.id}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Upload failed');
    } finally {
      setBusy(null);
      setProgress(0);
    }
  }

  async function importUrl() {
    setBusy('url');
    try {
      const res = await fetch('/api/videos', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ url }) });
      const body = await res.json();
      if (!res.ok) throw new Error(body?.error?.message ?? 'Import failed');
      toast.success('Importing video');
      router.push(`/video/${body.video.id}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Import failed');
    } finally {
      setBusy(null);
    }
  }

  async function previewUrl() {
    const res = await fetch('/api/ingest/resolve-url', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ url }) });
    setResolve(await res.json());
  }

  return (
    <main className="mx-auto max-w-2xl px-6 py-10">
      <h1 className="text-2xl font-bold">Add a video</h1>
      <p className="mb-8 text-sm text-muted-foreground">Upload a file or import a permitted public URL.</p>

      <Card className="mb-6">
        <CardHeader><CardTitle>Upload</CardTitle></CardHeader>
        <CardContent>
          <div
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files?.[0]; if (f) uploadFile(f); }}
            onClick={() => fileRef.current?.click()}
            className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed p-10 text-center transition-colors ${drag ? 'border-primary bg-primary/5' : 'border-white/10'}`}
          >
            <Upload className="h-8 w-8 text-primary" />
            <p className="mt-3 font-medium">Drop a video here or click to browse</p>
            <p className="mt-1 text-xs text-muted-foreground">MP4, MOV, WebM, MKV, M4V · up to 10 GB</p>
            <input ref={fileRef} type="file" accept="video/*" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) uploadFile(f); }} />
          </div>
          {busy === 'upload' && <Progress value={progress} className="mt-4" />}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Import from URL</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="flex gap-2">
            <div className="relative flex-1">
              <Link2 className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://youtube.com/watch?v=…" className="pl-9" />
            </div>
            <Button variant="outline" onClick={previewUrl} disabled={!url || busy !== null}>Check</Button>
            <Button onClick={importUrl} disabled={!url || busy !== null}>{busy === 'url' ? <Loader2 className="animate-spin" /> : 'Import'}</Button>
          </div>
          {resolve && (
            <div className="rounded-lg border border-white/10 bg-surface p-3 text-sm">
              <div className="flex items-center gap-2">
                {resolve.permitted ? <Check className="h-4 w-4 text-accent" /> : <X className="h-4 w-4 text-destructive" />}
                <span>{resolve.permitted ? 'Can be imported' : resolve.reason ?? 'Cannot be imported'}</span>
                {resolve.provider && <Badge variant="outline">{resolve.provider}</Badge>}
              </div>
            </div>
          )}
          <p className="text-xs text-muted-foreground">We only analyze public videos you have the rights to. Private, login-gated, DRM-protected, paid and live streams are refused.</p>
        </CardContent>
      </Card>
    </main>
  );
}
