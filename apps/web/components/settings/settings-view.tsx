'use client';

import { useQuery, useQueryClient } from '@tanstack/react-query';
import { CheckCircle2, ExternalLink, Loader2, Plug, XCircle } from 'lucide-react';
import { useSearchParams } from 'next/navigation';
import { useEffect } from 'react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

interface PlatformInfo {
  platform: string;
  label: string;
  configured: boolean;
  setupHint: string | null;
}

interface SocialAccountRow {
  id: string;
  platform: string;
  displayName: string | null;
  username: string | null;
  avatarUrl: string | null;
  status: string;
  expiresAt: string | null;
  lastError: string | null;
}

interface PublicationRow {
  id: string;
  platform: string;
  title: string;
  status: string;
  platformUrl: string | null;
  error: string | null;
  createdAt: string;
  account: { displayName: string | null; username: string | null } | null;
}

const STATUS_TONE: Record<string, string> = {
  PUBLISHED: 'text-accent',
  PROCESSING: 'text-primary',
  UPLOADING: 'text-primary',
  QUEUED: 'text-muted-foreground',
  SCHEDULED: 'text-muted-foreground',
  FAILED: 'text-destructive',
};

export function SettingsView() {
  const queryClient = useQueryClient();
  const params = useSearchParams();

  const { data: platformData } = useQuery({
    queryKey: ['social-platforms'],
    queryFn: async () => (await fetch('/api/social/platforms')).json() as Promise<{ platforms: PlatformInfo[] }>,
  });
  const { data: accountData } = useQuery({
    queryKey: ['social-accounts'],
    queryFn: async () => (await fetch('/api/social/accounts')).json() as Promise<{ accounts: SocialAccountRow[] }>,
  });
  const { data: publicationData } = useQuery({
    queryKey: ['publications'],
    queryFn: async () => (await fetch('/api/publications')).json() as Promise<{ publications: PublicationRow[] }>,
    refetchInterval: 10_000,
  });

  // Surface the OAuth callback outcome.
  useEffect(() => {
    const connected = params.get('connected');
    const error = params.get('error');
    const detail = params.get('detail');
    if (connected) {
      toast.success(`${connected} connected`);
      void queryClient.invalidateQueries({ queryKey: ['social-accounts'] });
    }
    if (error) {
      const friendly: Record<string, string> = {
        denied: 'Authorization was cancelled or denied.',
        state_mismatch: 'The authorization could not be verified. Try connecting again.',
        missing_state: 'The authorization session expired. Try connecting again.',
        not_configured: 'That platform is not configured on this instance.',
        connect_failed: detail ?? 'Could not complete the connection.',
        unknown_platform: 'Unknown platform.',
      };
      toast.error(friendly[error] ?? detail ?? 'Could not connect that account.');
    }
  }, [params, queryClient]);

  async function disconnect(id: string) {
    const res = await fetch(`/api/social/accounts?id=${id}`, { method: 'DELETE' });
    if (!res.ok) {
      toast.error('Could not disconnect that account');
      return;
    }
    toast.success('Account disconnected');
    void queryClient.invalidateQueries({ queryKey: ['social-accounts'] });
  }

  const platforms = platformData?.platforms ?? [];
  const accounts = accountData?.accounts ?? [];
  const publications = publicationData?.publications ?? [];

  return (
    <main className="mx-auto max-w-4xl px-6 py-10">
      <h1 className="text-2xl font-bold">Connected accounts</h1>
      <p className="mb-8 text-sm text-muted-foreground">
        Connect the channels ViralCut may publish to. Tokens are encrypted at rest and never sent to
        your browser.
      </p>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {platforms.map((p) => {
          const linked = accounts.filter((a) => a.platform === p.platform);
          return (
            <Card key={p.platform} className="h-full">
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base">{p.label}</CardTitle>
                  {p.configured ? (
                    <Badge variant="accent">ready</Badge>
                  ) : (
                    <Badge variant="outline">needs setup</Badge>
                  )}
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                {linked.length > 0 ? (
                  <ul className="space-y-2">
                    {linked.map((a) => (
                      <li key={a.id} className="flex items-center justify-between gap-2 rounded-md bg-surface p-2">
                        <span className="min-w-0 truncate text-sm">
                          {a.displayName ?? a.username ?? a.platform}
                          {a.status !== 'CONNECTED' && (
                            <span className="ml-2 text-xs text-amber-400">{a.status.toLowerCase()}</span>
                          )}
                        </span>
                        <button
                          onClick={() => disconnect(a.id)}
                          className="shrink-0 text-xs text-muted-foreground hover:text-destructive"
                        >
                          Disconnect
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-muted-foreground">
                    {p.configured ? 'No account connected yet.' : (p.setupHint ?? 'Not configured.')}
                  </p>
                )}
                <Button
                  asChild
                  size="sm"
                  variant={p.configured ? 'outline' : 'ghost'}
                  className="w-full gap-2"
                  {...(!p.configured ? { disabled: true } : {})}
                >
                  <a href={`/api/social/connect/${p.platform.toLowerCase()}`}>
                    <Plug className="h-4 w-4" />
                    {linked.length > 0 ? 'Add another' : `Connect ${p.label}`}
                  </a>
                </Button>
              </CardContent>
            </Card>
          );
        })}
      </div>

      <h2 className="mb-4 mt-12 text-xl font-bold">Recent publishing</h2>
      {publications.length === 0 ? (
        <Card className="p-10 text-center text-sm text-muted-foreground">
          Nothing published yet. Open a rendered clip and choose “Publish”.
        </Card>
      ) : (
        <Card>
          <CardContent className="divide-y divide-white/5 p-0">
            {publications.map((pub) => (
              <div key={pub.id} className="flex items-center justify-between gap-4 p-4">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{pub.title}</p>
                  <p className="text-xs text-muted-foreground">
                    {pub.platform} · {pub.account?.displayName ?? pub.account?.username ?? 'account'} ·{' '}
                    {new Date(pub.createdAt).toLocaleString()}
                  </p>
                  {pub.error && <p className="mt-1 text-xs text-destructive">{pub.error}</p>}
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <span className={`text-xs font-medium ${STATUS_TONE[pub.status] ?? 'text-muted-foreground'}`}>
                    {pub.status.toLowerCase()}
                  </span>
                  {pub.status === 'PROCESSING' && <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />}
                  {pub.status === 'PUBLISHED' && <CheckCircle2 className="h-3.5 w-3.5 text-accent" />}
                  {pub.status === 'FAILED' && <XCircle className="h-3.5 w-3.5 text-destructive" />}
                  {pub.platformUrl && (
                    <a href={pub.platformUrl} target="_blank" rel="noreferrer">
                      <ExternalLink className="h-3.5 w-3.5 text-muted-foreground hover:text-foreground" />
                    </a>
                  )}
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </main>
  );
}
