'use client';

import { Loader2, Send } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Progress } from '@/components/ui/progress';
import { useJobStream } from '@/hooks/use-job-stream';

interface AccountRow {
  id: string;
  platform: string;
  displayName: string | null;
  username: string | null;
  status: string;
}

const PRIVACY = [
  { value: 'PUBLIC', label: 'Public' },
  { value: 'UNLISTED', label: 'Unlisted' },
  { value: 'PRIVATE', label: 'Private' },
];

/**
 * Publish one clip to one connected account.
 *
 * Privacy support differs per platform (TikTok has no unlisted, Instagram only
 * publishes publicly) — the adapter refuses an unsupported combination with a
 * clear message rather than silently changing what the user asked for.
 */
export function PublishPanel({ clipId, defaultTitle }: { clipId: string; defaultTitle: string }) {
  const [accounts, setAccounts] = useState<AccountRow[] | null>(null);
  const [accountId, setAccountId] = useState('');
  const [title, setTitle] = useState(defaultTitle);
  const [description, setDescription] = useState('');
  const [tags, setTags] = useState('');
  const [privacy, setPrivacy] = useState('PUBLIC');
  const [jobId, setJobId] = useState<string | null>(null);
  const { latest } = useJobStream(jobId);

  async function loadAccounts() {
    const res = await fetch('/api/social/accounts');
    if (!res.ok) return;
    const body = (await res.json()) as { accounts: AccountRow[] };
    const connected = body.accounts.filter((a) => a.status === 'CONNECTED');
    setAccounts(connected);
    if (connected[0]) setAccountId(connected[0].id);
  }

  async function publish() {
    if (!accountId) {
      toast.error('Choose an account to publish to');
      return;
    }
    const res = await fetch(`/api/clips/${clipId}/publish`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        accountId,
        title,
        description,
        tags: tags.split(',').map((t) => t.trim()).filter(Boolean),
        privacy,
      }),
    });
    const body = await res.json();
    if (!res.ok) {
      toast.error(body?.error?.message ?? 'Could not queue publishing');
      return;
    }
    setJobId(body.jobId);
    toast.success('Publishing queued');
  }

  const running = Boolean(jobId) && latest?.type !== 'done' && latest?.type !== 'error';

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle className="text-base">Publish</CardTitle>
        {accounts === null && (
          <Button size="sm" variant="ghost" onClick={loadAccounts}>
            Load accounts
          </Button>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        {accounts !== null && accounts.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No connected accounts.{' '}
            <a href="/settings" className="text-primary hover:underline">
              Connect one
            </a>{' '}
            to publish directly.
          </p>
        )}

        {accounts !== null && accounts.length > 0 && (
          <>
            <div>
              <Label className="mb-2 block">Account</Label>
              <div className="flex flex-wrap gap-2">
                {accounts.map((a) => (
                  <button
                    key={a.id}
                    onClick={() => setAccountId(a.id)}
                    className={`rounded-md px-3 py-1.5 text-sm ${
                      accountId === a.id ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground'
                    }`}
                  >
                    {a.platform.toLowerCase()} · {a.displayName ?? a.username ?? 'account'}
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="pub-title">Title</Label>
              <Input id="pub-title" value={title} onChange={(e) => setTitle(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pub-desc">Description</Label>
              <Input id="pub-desc" value={description} onChange={(e) => setDescription(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pub-tags">Tags (comma separated)</Label>
              <Input id="pub-tags" value={tags} onChange={(e) => setTags(e.target.value)} placeholder="startup, hiring" />
            </div>

            <div>
              <Label className="mb-2 block">Visibility</Label>
              <div className="flex gap-2">
                {PRIVACY.map((p) => (
                  <button
                    key={p.value}
                    onClick={() => setPrivacy(p.value)}
                    className={`rounded-md px-3 py-1.5 text-sm ${
                      privacy === p.value ? 'bg-secondary text-secondary-foreground' : 'bg-muted text-muted-foreground'
                    }`}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                TikTok maps unlisted to “only me”; Instagram publishes publicly or not at all.
              </p>
            </div>

            <Button onClick={publish} disabled={running} className="w-full gap-2">
              {running ? <Loader2 className="animate-spin" /> : <Send />} Publish now
            </Button>
          </>
        )}

        {jobId && latest && (
          <div className="rounded-md bg-surface p-3 text-sm">
            {running && (
              <>
                <div className="mb-2 flex items-center gap-2">
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
                  {latest.message ?? latest.stage ?? 'Publishing…'}
                </div>
                <Progress value={latest.progress ?? 0} />
              </>
            )}
            {latest.type === 'done' && (
              <div className="flex items-center gap-2 text-accent">
                <Badge variant="accent">published</Badge> {latest.message}
              </div>
            )}
            {latest.type === 'error' && <p className="text-destructive">{latest.message}</p>}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
