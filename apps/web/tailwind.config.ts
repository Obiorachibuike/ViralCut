import type { Config } from 'tailwindcss';
import preset from '@viralcut/config/tailwind.preset.js';

export default {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  presets: [preset as any],
  content: [
    './app/**/*.{ts,tsx}',
    './components/**/*.{ts,tsx}',
    './lib/**/*.{ts,tsx}',
    '../../packages/shared/src/**/*.{ts,tsx}',
  ],
} satisfies Config;
