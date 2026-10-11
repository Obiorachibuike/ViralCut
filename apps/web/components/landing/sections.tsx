'use client';

import { motion } from 'framer-motion';
import {
  BadgeCheck, Clapperboard, FileVideo, Link2, MessageSquareText, Monitor,
  Quote, Scissors, Sparkles, Target, Video, Wand2, ZoomIn,
} from 'lucide-react';
import type { ReactNode } from 'react';

import { Badge } from '@/components/ui/badge';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

export function Section({ id, className, children }: { id?: string; className?: string; children: ReactNode }) {
  return <section id={id} className={`mx-auto w-full max-w-6xl px-6 py-20 ${className ?? ''}`}>{children}</section>;
}

export function Heading({ eyebrow, title, sub }: { eyebrow: string; title: string; sub?: string }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: '-80px' }}
      transition={{ duration: 0.5 }}
      className="mb-12 text-center"
    >
      <span className="text-sm font-semibold uppercase tracking-widest text-primary">{eyebrow}</span>
      <h2 className="mt-3 text-3xl font-bold sm:text-4xl">{title}</h2>
      {sub ? <p className="mx-auto mt-4 max-w-2xl text-muted-foreground">{sub}</p> : null}
    </motion.div>
  );
}

const FEATURES = [
  { icon: Sparkles, title: 'AI moment discovery', text: 'Finds hooks, emotion, story, value, debate and curiosity — not fixed-length cuts.' },
  { icon: Scissors, title: 'Automatic clipping', text: 'Cut from hook to payoff with natural boundaries and 1–5s padding.' },
  { icon: ZoomIn, title: 'Smart reframing', text: 'Auto, center, active-speaker tracking or split-screen into any aspect ratio.' },
  { icon: MessageSquareText, title: 'Captions', text: 'Six animated word-level styles you can fully restyle.' },
  { icon: Wand2, title: 'AI hooks & titles', text: 'Three hook and three title options per clip, editable before render.' },
  { icon: Monitor, title: 'Browser editor', text: 'Trim, edit captions, restyle, add music and a logo, then export.' },
];

export function FeatureGrid() {
  return (
    <Section id="how-it-works">
      <Heading eyebrow="How it works" title="One upload. A queue of ready clips." sub="ViralCut handles the whole pipeline so you never touch a timeline." />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {FEATURES.map((f) => (
          <motion.div key={f.title} initial={{ opacity: 0, y: 16 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ duration: 0.4 }}>
            <Card className="h-full transition-colors hover:border-primary/40">
              <CardHeader>
                <div className="mb-2 inline-flex h-10 w-10 items-center justify-center rounded-lg bg-primary/15"><f.icon className="h-5 w-5 text-primary" /></div>
                <CardTitle className="text-lg">{f.title}</CardTitle>
              </CardHeader>
              <CardContent><CardDescription>{f.text}</CardDescription></CardContent>
            </Card>
          </motion.div>
        ))}
      </div>
    </Section>
  );
}

const SCORES = [
  { label: 'Hook strength', value: 88, color: 'from-primary to-secondary' },
  { label: 'Curiosity', value: 76 },
  { label: 'Emotional impact', value: 81 },
  { label: 'Story arc', value: 70 },
  { label: 'Value & clarity', value: 84 },
  { label: 'Shareability', value: 92, color: 'from-accent to-primary' },
];

export function MomentDiscovery() {
  return (
    <Section id="discovery" className="border-y border-white/5 bg-surface/40">
      <Heading eyebrow="AI moment discovery" title="Ranked by why it will perform" sub="Every candidate is scored across eight dimensions and de-duplicated to the single strongest version." />
      <div className="grid gap-8 lg:grid-cols-2">
        <Card className="p-6">
          <div className="mb-4 flex items-center gap-3">
            <Badge variant="accent">Viral score 86</Badge>
            <Badge variant="outline">Business</Badge>
            <Badge variant="outline">Surprising</Badge>
          </div>
          <h3 className="text-lg font-semibold">“The biggest mistake I made hiring…”</h3>
          <p className="mt-1 text-sm text-muted-foreground">00:42 – 00:58 · strong hook, clear payoff, stands alone.</p>
          <div className="mt-6 space-y-3">
            {SCORES.map((s) => (
              <div key={s.label}>
                <div className="mb-1 flex justify-between text-xs text-muted-foreground"><span>{s.label}</span><span>{s.value}</span></div>
                <div className="h-2 overflow-hidden rounded-full bg-muted">
                  <motion.div initial={{ width: 0 }} whileInView={{ width: `${s.value}%` }} viewport={{ once: true }} transition={{ duration: 0.8 }} className={`h-full bg-gradient-to-r ${s.color ?? 'from-primary to-secondary'}`} />
                </div>
              </div>
            ))}
          </div>
        </Card>
        <div className="space-y-4">
          {[
            { icon: Sparkles, t: 'Hooks that stop the scroll', d: 'Opening lines, bold claims and contrarian takes.' },
            { icon: Target, t: 'Context-aware boundaries', d: 'Hook → context → payoff → natural end, never mid-word.' },
            { icon: FileVideo, t: 'Length-aware candidates', d: 'A 20-minute video yields 15–30; two hours can yield over a hundred.' },
          ].map((x) => (
            <Card key={x.t} className="flex items-start gap-4 p-5">
              <div className="mt-0.5 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-secondary/15"><x.icon className="h-4.5 w-4.5 text-secondary" /></div>
              <div><p className="font-medium">{x.t}</p><p className="text-sm text-muted-foreground">{x.d}</p></div>
            </Card>
          ))}
        </div>
      </div>
    </Section>
  );
}

export function Workflows() {
  const items = [
    { icon: Video, t: 'Podcasts & interviews' },
    { icon: MessageSquareText, t: 'Webinars & courses' },
    { icon: Clapperboard, t: 'Vlogs & long-form' },
    { icon: Quote, t: 'Conferences & talks' },
    { icon: Link2, t: 'Public URL import' },
    { icon: BadgeCheck, t: 'Rights-respecting by design' },
  ];
  return (
    <Section>
      <Heading eyebrow="Supported workflows" title="Built for the videos you already make" />
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
        {items.map((x) => (
          <Card key={x.t} className="flex items-center gap-3 p-4">
            <x.icon className="h-5 w-5 text-primary" />
            <span className="text-sm">{x.t}</span>
          </Card>
        ))}
      </div>
    </Section>
  );
}

export function TextToVideo() {
  return (
    <Section id="text-to-video">
      <Heading
        eyebrow="Text to video"
        title="No footage? Generate it."
        sub="Describe the shot and ViralCut creates it, then runs the same moment discovery and clipping pipeline on the result."
      />
      <div className="grid gap-8 lg:grid-cols-2">
        <Card className="p-6">
          <Label className="mb-2 block text-xs uppercase tracking-wide text-muted-foreground">Prompt</Label>
          <p className="rounded-md bg-surface p-3 text-sm italic">
            “A golden retriever surfing a turquoise wave at sunrise, slow motion, 35mm”
          </p>
          <div className="mt-4 flex items-center gap-2">
            <Badge variant="default">9:16</Badge>
            <Badge variant="outline">5s</Badge>
            <Badge variant="accent">generated</Badge>
          </div>
          <p className="mt-4 text-sm text-muted-foreground">
            Pluggable backends: run the self-hosted LongCat-Video GPU worker, or a hosted model. If
            none is configured the app says so instead of faking a result.
          </p>
        </Card>
        <div className="space-y-4">
          {[
            { icon: Sparkles, t: 'Prompt in, footage out', d: 'Aspect ratio, duration and negative prompts are all configurable.' },
            { icon: Clapperboard, t: 'Treated as real source', d: 'Generated video is probed, stored and analysed like an upload.' },
            { icon: Scissors, t: 'Then clip it', d: 'Moment discovery, captions, hooks and reframing work unchanged.' },
          ].map((x) => (
            <Card key={x.t} className="flex items-start gap-4 p-5">
              <div className="mt-0.5 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/15">
                <x.icon className="h-4 w-4 text-primary" />
              </div>
              <div>
                <p className="font-medium">{x.t}</p>
                <p className="text-sm text-muted-foreground">{x.d}</p>
              </div>
            </Card>
          ))}
        </div>
      </div>
    </Section>
  );
}

const NETWORKS = [
  { name: 'YouTube', note: 'Resumable upload, public / unlisted / private' },
  { name: 'TikTok', note: 'Content Posting API with chunked upload' },
  { name: 'Facebook', note: 'Page video posts via the Graph API' },
  { name: 'Instagram', note: 'Reels published to a Business account' },
  { name: 'LinkedIn', note: 'Video posts to your profile' },
  { name: 'X', note: 'Video posts with chunked media upload' },
];

export function AutoPublish() {
  return (
    <Section id="publish" className="border-y border-white/5 bg-surface/40">
      <Heading
        eyebrow="Auto-publishing"
        title="Ship the clip without leaving the editor"
        sub="Connect your accounts once, then publish a rendered clip straight to your channels with title, description, tags and visibility."
      />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {NETWORKS.map((n) => (
          <Card key={n.name} className="p-5">
            <div className="flex items-center gap-2">
              <BadgeCheck className="h-4 w-4 text-accent" />
              <span className="font-medium">{n.name}</span>
            </div>
            <p className="mt-2 text-sm text-muted-foreground">{n.note}</p>
          </Card>
        ))}
      </div>
      <p className="mt-8 text-center text-sm text-muted-foreground">
        Tokens are encrypted at rest and never reach your browser. Each platform needs its own
        developer app — ViralCut tells you exactly what is missing until it is connected.
      </p>
    </Section>
  );
}
