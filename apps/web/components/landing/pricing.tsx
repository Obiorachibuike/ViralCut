'use client';

import { motion } from 'framer-motion';
import { Check } from 'lucide-react';
import Link from 'next/link';

import { PLANS } from '@viralcut/shared';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

export function Pricing() {
  return (
    <section id="pricing" className="border-y border-white/5 bg-surface/40">
      <div className="mx-auto w-full max-w-6xl px-6 py-20">
        <div className="mb-12 text-center">
          <span className="text-sm font-semibold uppercase tracking-widest text-primary">Pricing</span>
          <h2 className="mt-3 text-3xl font-bold sm:text-4xl">Start free. Scale when you are ready.</h2>
          <p className="mt-4 text-muted-foreground">Every plan includes AI moment discovery and the editor.</p>
        </div>
        <div className="grid gap-6 lg:grid-cols-3">
          {PLANS.map((plan) => {
            const isPro = plan.tier === 'PRO';
            return (
              <motion.div
                key={plan.tier}
                initial={{ opacity: 0, y: 16 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.4 }}
              >
                <Card className={`relative h-full p-6 ${isPro ? 'animated-border border-primary/50' : ''}`}>
                  <CardHeader>
                    <div className="flex items-center justify-between">
                      <CardTitle>{plan.label}</CardTitle>
                      <span className="text-2xl font-bold">
                        {plan.priceMonthlyUsd === 0 ? 'Free' : `$${plan.priceMonthlyUsd}`}
                        <span className="text-sm font-normal text-muted-foreground">/mo</span>
                      </span>
                    </div>
                    <p className="text-sm text-muted-foreground">{plan.blurb}</p>
                  </CardHeader>
                  <CardContent>
                    <ul className="mb-6 space-y-2 text-sm">
                      {plan.features.map((f) => (
                        <li key={f} className="flex items-start gap-2">
                          <Check className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
                          {f}
                        </li>
                      ))}
                    </ul>
                    <Button asChild className="w-full" variant={isPro ? 'default' : 'outline'}>
                      <Link href="/register">{plan.tier === 'FREE' ? 'Start free' : `Choose ${plan.label}`}</Link>
                    </Button>
                  </CardContent>
                </Card>
              </motion.div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
