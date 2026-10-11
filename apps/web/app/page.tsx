import { Demo } from '@/components/landing/demo';
import {
  AutoPublish,
  FeatureGrid,
  Heading,
  MomentDiscovery,
  Section,
  TextToVideo,
  Workflows,
} from '@/components/landing/sections';
import { Faq } from '@/components/landing/faq';
import { Hero } from '@/components/landing/hero';
import { FinalCta, Footer } from '@/components/landing/footer';
import { Nav } from '@/components/landing/nav';
import { Pricing } from '@/components/landing/pricing';

export default function Home() {
  return (
    <main className="min-h-screen">
      <Nav />
      <Hero />
      <Demo />
      <FeatureGrid />
      <MomentDiscovery />
      <TextToVideo />
      <Reframing />
      <AutoPublish />
      <Workflows />
      <Pricing />
      <Faq />
      <FinalCta />
      <Footer />
    </main>
  );
}

function Reframing() {
  const ratios = [
    { label: '9:16 · TikTok / Reels / Shorts', box: 'aspect-[9/16]' },
    { label: '1:1 · Feed', box: 'aspect-square' },
    { label: '4:5 · Portrait', box: 'aspect-[4/5]' },
    { label: '16:9 · YouTube', box: 'aspect-video' },
  ];
  return (
    <Section>
      <Heading eyebrow="Smart reframing" title="One video, every format" sub="Auto, center, active-speaker tracking or split-screen — reframed to any aspect ratio without losing the subject." />
      <div className="flex flex-wrap items-end justify-center gap-6">
        {ratios.map((r) => (
          <div key={r.label} className="flex flex-col items-center gap-3">
            <div className={`w-28 rounded-lg border border-white/10 bg-gradient-to-br from-primary/30 to-secondary/30 ${r.box}`} />
            <span className="text-xs text-muted-foreground">{r.label}</span>
          </div>
        ))}
      </div>
    </Section>
  );
}
