/**
 * Social publishing contract.
 *
 * One interface, one adapter per platform. Adding a network means adding a file
 * here and registering it — nothing else in the app changes. An adapter is
 * `configured()` only when its OAuth app credentials exist, so the UI can tell
 * the user exactly what is missing instead of failing at publish time.
 */

export type SocialPlatformId = 'YOUTUBE' | 'TIKTOK' | 'FACEBOOK' | 'INSTAGRAM' | 'LINKEDIN' | 'X';

export const SOCIAL_PLATFORMS: SocialPlatformId[] = [
  'YOUTUBE',
  'TIKTOK',
  'FACEBOOK',
  'INSTAGRAM',
  'LINKEDIN',
  'X',
];

export type PublishPrivacy = 'PUBLIC' | 'UNLISTED' | 'PRIVATE';

export interface PublishInput {
  title: string;
  description?: string | null;
  tags?: string[];
  privacy: PublishPrivacy;
  /** Per-platform extras: playlistId, categoryId, allowComments, disableDuet, ... */
  options?: Record<string, unknown>;
}

export interface PublishMaterial {
  /** Local path the worker downloaded from storage. Preferred when supported. */
  filePath?: string;
  /** Public URL for platforms that pull server-side (Instagram, TikTok PULL_FROM_URL). */
  fileUrl?: string;
  mimeType?: string;
  sizeBytes?: number;
  durationMs?: number;
}

export interface PublishOutcome {
  platformPostId: string;
  platformUrl?: string | null;
  /** PROCESSING = the platform accepted it but is still transcoding. */
  status: 'PUBLISHED' | 'PROCESSING';
  raw?: unknown;
}

export interface PlatformToken {
  accessToken: string;
  refreshToken?: string | null;
  expiresAt?: Date | null;
  tokenType?: string;
}

/** What we learn about the account during the OAuth callback. */
export interface ConnectedIdentity extends PlatformToken {
  platformUserId: string;
  username?: string | null;
  displayName?: string | null;
  avatarUrl?: string | null;
  scopes: string[];
  meta?: Record<string, unknown>;
}

export interface SocialPublisher {
  platform: SocialPlatformId;
  label: string;
  /** Plain-language instruction shown when the platform is not configured. */
  setupHint: string;

  configured(): boolean;

  /**
   * Where to send the user to grant access. `codeChallenge` is required by
   * PKCE flows (X) and ignored elsewhere.
   */
  authorizeUrl(state: string, redirectUri: string, codeChallenge?: string): string;

  /**
   * Trade the callback code for tokens, and identify the account.
   * `extras` carries per-flow values stashed at authorize time (e.g. the PKCE
   * code verifier X requires).
   */
  connect(
    code: string,
    redirectUri: string,
    extras?: Record<string, string>,
  ): Promise<ConnectedIdentity>;

  /** Optional token refresh; adapters without refresh tokens omit it. */
  refresh?(token: PlatformToken): Promise<PlatformToken>;

  /** Upload + publish one clip. Throws PublishError with a user-safe message. */
  publish(token: PlatformToken, input: PublishInput, material: PublishMaterial): Promise<PublishOutcome>;
}

export class PublishError extends Error {
  constructor(
    message: string,
    readonly opts: { code?: string; status?: number; retryable?: boolean; logDetail?: string } = {},
  ) {
    super(message);
    this.name = 'PublishError';
  }
}

/** Human labels used across the UI. */
export const PLATFORM_LABELS: Record<SocialPlatformId, string> = {
  YOUTUBE: 'YouTube',
  TIKTOK: 'TikTok',
  FACEBOOK: 'Facebook',
  INSTAGRAM: 'Instagram',
  LINKEDIN: 'LinkedIn',
  X: 'X',
};
