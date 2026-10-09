import { Clapperboard } from 'lucide-react';
import Link from 'next/link';

import { Button } from '@/components/ui/button';

export function FinalCta() {
  return (
    <section className="mx-auto w-full max-w-6xl px-6 py-20">
      <div className="animated-border glass-card relative overflow-hidden p-12 text-center">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(139,92,246,0.15),transparent_60%)]" />
        <h2 className="relative text-3xl font-bold sm:text-4xl">Ready to find your next viral moment?</h2>
        <p className="relative mx-auto mt-4 max-w-xl text-muted-foreground">Upload a video, get a ranked list of moments and export polished vertical clips — all in one place.</p>
        <div className="relative mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
          <Button asChild size="xl"><Link href="/register">Start Creating</Link></Button>
          <Button asChild size="xl" variant="outline"><Link href="/login">Sign in</Link></Button>
        </div>
      </div>
    </section>
  );
}

export function Footer() {
  return (
    <footer className="border-t border-white/5">
      <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-6 px-6 py-10 sm:flex-row">
        <Link href="/" className="flex items-center gap-2 font-semibold">
          <span className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-primary to-secondary"><Clapperboard className="h-4 w-4" /></span>
          ViralCut
        </Link>
        <p className="text-sm text-muted-foreground">© {new Date().getFullYear()} ViralCut. You own everything you create.</p>
        <div className="flex gap-6 text-sm text-muted-foreground">
          <Link href="#pricing" className="hover:text-foreground">Pricing</Link>
          <Link href="#faq" className="hover:text-foreground">FAQ</Link>
        </div>
      </div>
    </footer>
  );
}
