import { Suspense } from 'react';

import { SettingsView } from '@/components/settings/settings-view';
import { Skeleton } from '@/components/ui/skeleton';

export default function SettingsPage() {
  return (
    <Suspense
      fallback={
        <main className="mx-auto max-w-4xl px-6 py-10">
          <Skeleton className="mb-2 h-8 w-64" />
          <Skeleton className="mb-8 h-4 w-96" />
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-40" />
            ))}
          </div>
        </main>
      }
    >
      <SettingsView />
    </Suspense>
  );
}
