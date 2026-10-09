'use client';

import * as Accordion from '@radix-ui/react-accordion';
import { ChevronDown } from 'lucide-react';

const FAQ = [
  { q: 'What video formats can I upload?', a: 'MP4, MOV, WebM, MKV and M4V up to 10 GB. Uploads are chunked and resumable, with progress and format validation.' },
  { q: 'Can I import a video by URL?', a: 'Yes, for public videos that permit third-party use. Private, login-gated, DRM-protected, paid or live streams are refused.' },
  { q: 'How does moment discovery work?', a: 'We transcribe the audio, detect speakers and scenes, then score segments across hook, curiosity, emotion, story, value, shareability, standalone clarity and visual quality.' },
  { q: 'Do I own the clips?', a: 'Yes. Everything you create is yours and private to your account.' },
  { q: 'Do you respect copyright?', a: 'Absolutely. We only analyze content you have the rights to and never bypass authentication, DRM or paywalls.' },
  { q: 'Which aspect ratios are supported?', a: '9:16, 1:1, 16:9 and 4:5, with presets for TikTok, Instagram Reels, YouTube Shorts, YouTube and LinkedIn.' },
];

export function Faq() {
  return (
    <section id="faq" className="mx-auto w-full max-w-3xl px-6 py-20">
      <div className="mb-12 text-center">
        <span className="text-sm font-semibold uppercase tracking-widest text-primary">FAQ</span>
        <h2 className="mt-3 text-3xl font-bold sm:text-4xl">Questions, answered</h2>
      </div>
      <Accordion.Root type="single" collapsible className="space-y-3">
        {FAQ.map((item, i) => (
          <div key={item.q} className="overflow-hidden rounded-xl border border-white/10 bg-card/50">
            <Accordion.Item value={String(i)}>
              <Accordion.Header>
                <Accordion.Trigger className="group flex w-full items-center justify-between gap-4 px-5 py-4 text-left font-medium">
                  {item.q}
                  <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-data-[state=open]:rotate-180" />
                </Accordion.Trigger>
              </Accordion.Header>
              <Accordion.Content className="overflow-hidden data-[state=open]:animate-accordion-down">
                <p className="px-5 pb-4 text-sm text-muted-foreground">{item.a}</p>
              </Accordion.Content>
            </Accordion.Item>
          </div>
        ))}
      </Accordion.Root>
    </section>
  );
}
