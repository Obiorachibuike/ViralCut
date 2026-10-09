'use client';

import { motion } from 'framer-motion';
import { ArrowRight, Check, Link2, Upload, Wand2 } from 'lucide-react';
import Link from 'next/link';

import { Button } from '@/components/ui/button';

export function Hero() {
  return (
    <section className="relative overflow-hidden">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top,rgba(99,102,241,0.18),transparent_55%)]" />
      <div className="pointer-events-none absolute -top-24 left-1/2 h-72 w-72 -translate-x-1/2 rounded-full bg-secondary/20 blur-[120px]" />
      <div className="relative mx-auto flex max-w-5xl flex-col items-center px-6 pt-28 pb-16 text-center">
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="mb-6 inline-flex items-center gap-2 rounded-full border border-white/10 bg-card/60 px-4 py-1.5 text-sm text-muted-foreground backdrop-blur"
        >
          <Wand2 className="h-4 w-4 text-primary" /> AI moment discovery for long-form video
        </motion.div>
        <motion.h1
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.05 }}
          className="text-balance text-5xl font-extrabold tracking-tight sm:text-6xl"
        >
          Turn long videos into <span className="text-gradient">viral moments</span>
        </motion.h1>
        <motion.p
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.15 }}
          className="mt-6 max-w-2xl text-balance text-lg text-muted-foreground"
        >
          Upload a video or paste a public video URL. ViralCut analyzes the entire conversation and
          finds the moments people will actually want to watch.
        </motion.p>
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.25 }}
          className="mt-8 flex flex-col gap-3 sm:flex-row"
        >
          <Button asChild size="xl" className="gap-2">
            <Link href="/register">Start Creating <ArrowRight /></Link>
          </Button>
          <Button asChild size="xl" variant="outline">
            <Link href="#how-it-works">See how it works</Link>
          </Button>
        </motion.div>
        <motion.ul
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.6, delay: 0.4 }}
          className="mt-8 flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-sm text-muted-foreground"
        >
          {['9:16, 1:1, 16:9 & 4:5', 'Word-level captions', 'AI hooks & titles', 'Speaker tracking'].map((f) => (
            <li key={f} className="flex items-center gap-1.5"><Check className="h-4 w-4 text-accent" /> {f}</li>
          ))}
        </motion.ul>
        <div className="mt-6 flex items-center gap-2 text-xs text-muted-foreground">
          <Upload className="h-3.5 w-3.5" /> upload your own file
          <span className="opacity-40">or</span>
          <Link2 className="h-3.5 w-3.5" /> import a permitted public URL
        </div>
      </div>
    </section>
  );
}
