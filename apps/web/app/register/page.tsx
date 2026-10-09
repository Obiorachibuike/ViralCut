import { Clapperboard } from 'lucide-react';
import Link from 'next/link';

import { AuthForm } from '@/components/auth/auth-form';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

export default function RegisterPage() {
  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <div className="w-full max-w-sm">
        <Link href="/" className="mb-8 flex items-center justify-center gap-2 text-lg font-semibold">
          <span className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-primary to-secondary"><Clapperboard className="h-5 w-5" /></span>
          ViralCut
        </Link>
        <Card className="p-2">
          <CardHeader><CardTitle>Create your account</CardTitle><CardDescription>Start turning long videos into viral moments.</CardDescription></CardHeader>
          <CardContent><AuthForm mode="register" /></CardContent>
        </Card>
      </div>
    </main>
  );
}
