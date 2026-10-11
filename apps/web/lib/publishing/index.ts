/**
 * Publisher registry.
 *
 * `getPublisher()` is the only entry point the rest of the app uses, so platform
 * support is a lookup rather than a switch scattered across routes. Every
 * adapter is instantiated eagerly because they hold no state — only module-level
 * env reads — which keeps `configured()` cheap and side-effect free.
 */
import { facebookPublisher } from './facebook';
import { instagramPublisher } from './instagram';
import { linkedinPublisher } from './linkedin';
import { tiktokPublisher } from './tiktok';
import { xPublisher } from './x';
import { youtubePublisher } from './youtube';
import {
  PLATFORM_LABELS,
  PublishError,
  SOCIAL_PLATFORMS,
  type SocialPlatformId,
  type SocialPublisher,
} from './types';

const REGISTRY: Record<SocialPlatformId, SocialPublisher> = {
  YOUTUBE: youtubePublisher,
  TIKTOK: tiktokPublisher,
  FACEBOOK: facebookPublisher,
  INSTAGRAM: instagramPublisher,
  LINKEDIN: linkedinPublisher,
  X: xPublisher,
};

export function getPublisher(platform: SocialPlatformId): SocialPublisher {
  const publisher = REGISTRY[platform];
  if (!publisher) {
    throw new PublishError(`Unsupported platform: ${platform}`, { code: 'unsupported_platform' });
  }
  return publisher;
}

/** Capability matrix for the settings UI: what works now, and what is missing. */
export function describePlatforms() {
  return SOCIAL_PLATFORMS.map((platform) => {
    const publisher = getPublisher(platform);
    const configured = publisher.configured();
    return {
      platform,
      label: PLATFORM_LABELS[platform],
      configured,
      setupHint: configured ? null : publisher.setupHint,
    };
  });
}

export function isPlatform(platform: string): platform is SocialPlatformId {
  return (SOCIAL_PLATFORMS as string[]).includes(platform.toUpperCase());
}

export * from './types';
export { decryptToken, encryptToken } from './crypto';
