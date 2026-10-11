'use client';

import { motion } from 'framer-motion';
import { Check, Link2, Loader2, Upload, X } from 'lucide-react';
import Link from 'next/link';
import { useState } from 'react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card } from '@/components/ui/card';

interface ResolveResult {
  permitted?: boolean;
  provider?: string;
  kind?: string;
  reason?: string | null;
  isPrivate?: boolean;
  drmProtected?: boolean;
  requiresLogin?: boolean;
  isLive?: boolean;
}

export function Demo() {
  const [url, setUrl] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ResolveResult | null>(null);
  const [drag, setDrag] = useState(false);

  async function resolve() {
    setLoading(true);
    setResult(null);
    try {
      const res = await fetch('/api/ingest/resolve-url', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ url }),
      });
      setResult(await res.json());
    } catch {
      setResult({ permitted: false, reason: 'Could not analyze this URL' });
    } finally {
      setLoading(false);
    }
  }

  return (
    <section id="demo" className="mx-auto w-full max-w-3xl px-6 pb-8">
      <Card className="p-6 sm:p-8">
        <div
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); }}
          className={`flex flex-col items-center justify-center rounded-xl border-2 border-dashed p-8 text-center transition-colors ${drag ? 'border-primary bg-primary/5' : 'border-white/10'}`}
        >
          <Upload className="h-8 w-8 text-primary" />
          <p className="mt-3 font-medium">Drag a video here, or</p>
          <Button asChild size="sm" className="mt-3"><Link href="/register">Create an account to upload</Link></Button>
          <p className="mt-3 text-xs text-muted-foreground">MP4, MOV, WebM, MKV, M4V · up to 10 GB · resumable</p>
        </div>

        <div className="my-6 flex items-center gap-3 text-xs text-muted-foreground">
          <span className="h-px flex-1 bg-white/10" /> or paste a public URL <span className="h-px flex-1 bg-white/10" />
        </div>

        <div className="flex gap-2">
          <div className="relative flex-1">
            <Link2 className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://youtube.com/watch?v=…" className="pl-9" />
          </div>
          <Button onClick={resolve} disabled={loading || !url}>{loading ? <Loader2 className="animate-spin" /> : 'Check'}</Button>
        </div>

        {result && (
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="mt-4 rounded-lg border border-white/10 bg-surface p-4">
            <div className="flex items-center gap-2">
              {result.permitted ? <Check className="h-4 w-4 text-accent" /> : <X className="h-4 w-4 text-destructive" />}
              <span className="font-medium">{result.permitted ? 'This source can be imported' : 'This source can’t be imported'}</span>
              {result.provider && <Badge variant="outline">{result.provider}</Badge>}
            </div>
            {result.reason && <p className="mt-2 text-sm text-muted-foreground">{result.reason}</p>}
            <div className="mt-2 flex flex-wrap gap-2 text-xs text-muted-foreground">
              {result.isPrivate && <span>Private</span>}
              {result.requiresLogin && <span>Login required</span>}
              {result.drmProtected && <span>DRM protected</span>}
              {result.isLive && <span>Live stream</span>}
            </div>
          </motion.div>
        )}
      </Card>
    </section>
  );
}
