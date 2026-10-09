'use client';

import { Clapperboard, Menu, Moon, Sun, X } from 'lucide-react';
import Link from 'next/link';
import { useTheme } from 'next-themes';
import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';

const LINKS = [
  { href: '#how-it-works', label: 'How it works' },
  { href: '#discovery', label: 'Discovery' },
  { href: '/generate', label: 'Text to video' },
  { href: '#pricing', label: 'Pricing' },
  { href: '#faq', label: 'FAQ' },
];

export function Nav() {
  const [open, setOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const { resolvedTheme, setTheme } = useTheme();
  useEffect(() => setMounted(true), []);

  return (
    <header className="fixed inset-x-0 top-0 z-50 border-b border-white/5 bg-background/70 backdrop-blur-xl">
      <nav className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
        <Link href="/" className="flex items-center gap-2 font-semibold">
          <span className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-primary to-secondary"><Clapperboard className="h-4 w-4" /></span>
          ViralCut
        </Link>
        <div className="hidden items-center gap-6 md:flex">
          {LINKS.map((l) => (
            <Link key={l.href} href={l.href} className="text-sm text-muted-foreground transition-colors hover:text-foreground">{l.label}</Link>
          ))}
        </div>
        <div className="flex items-center gap-2">
          {mounted && (
            <Button variant="ghost" size="icon" onClick={() => setTheme(resolvedTheme === 'dark' ? 'light' : 'dark')} aria-label="Toggle theme">
              {resolvedTheme === 'dark' ? <Sun /> : <Moon />}
            </Button>
          )}
          <Button asChild variant="ghost" size="sm" className="hidden sm:inline-flex"><Link href="/login">Sign in</Link></Button>
          <Button asChild size="sm"><Link href="/register">Start free</Link></Button>
          <Button variant="ghost" size="icon" className="md:hidden" onClick={() => setOpen((o) => !o)} aria-label="Menu">{open ? <X /> : <Menu />}</Button>
        </div>
      </nav>
      {open && (
        <div className="border-t border-white/5 bg-background/95 px-6 py-4 md:hidden">
          {LINKS.map((l) => (
            <Link key={l.href} href={l.href} onClick={() => setOpen(false)} className="block py-2 text-sm text-muted-foreground">{l.label}</Link>
          ))}
        </div>
      )}
    </header>
  );
}
