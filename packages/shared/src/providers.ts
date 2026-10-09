import type { SourceKind } from './constants';

/**
 * Provider detection.
 *
 * The authoritative implementation lives in the Python backend
 * (`apps/api/providers/registry.py`) because that is where ingestion actually
 * happens. This copy exists so the frontend can label a pasted URL instantly
 * without a round-trip. Both sides are asserted against the same fixture set:
 * `packages/shared/src/__fixtures__/provider-cases.json`.
 */

export interface DetectedProvider {
  kind: SourceKind;
  provider: string;
  /** Canonical external id when one could be extracted (e.g. YouTube video id). */
  externalId: string | null;
  /** True when the platform is known to ViralCut with a dedicated adapter. */
  dedicated: boolean;
  /** True when ingestion is allowed at all (DRM / login walls are refused). */
  permitted: boolean;
  /** Human-readable reason when `permitted` is false. */
  reason?: string;
}

const YOUTUBE_HOSTS = [
  'youtube.com',
  'www.youtube.com',
  'm.youtube.com',
  'music.youtube.com',
  'youtu.be',
  'www.youtu.be',
  'youtube-nocookie.com',
  'www.youtube-nocookie.com',
];

const TIKTOK_HOSTS = ['tiktok.com', 'www.tiktok.com', 'vm.tiktok.com', 'vt.tiktok.com', 'm.tiktok.com'];
const FACEBOOK_HOSTS = ['facebook.com', 'www.facebook.com', 'm.facebook.com', 'web.facebook.com', 'fb.watch', 'fb.com'];

function parse(url: string): URL | null {
  try {
    return new URL(url.trim());
  } catch {
    return null;
  }
}

function hostOf(u: URL): string {
  return u.hostname.toLowerCase().replace(/\.$/, '');
}

function matches(host: string, candidates: string[]): boolean {
  return candidates.some((c) => host === c || host.endsWith(`.${c}`));
}

export function detectProvider(rawUrl: string): DetectedProvider {
  const u = parse(rawUrl);
  if (!u || (u.protocol !== 'http:' && u.protocol !== 'https:')) {
    return {
      kind: 'GENERIC',
      provider: 'unknown',
      externalId: null,
      dedicated: false,
      permitted: false,
      reason: 'That does not look like a valid http(s) URL.',
    };
  }

  const host = hostOf(u);

  if (matches(host, YOUTUBE_HOSTS)) {
    let id: string | null = null;
    if (host === 'youtu.be' || host.endsWith('.youtu.be')) {
      id = u.pathname.split('/').filter(Boolean)[0] ?? null;
    } else if (u.pathname.startsWith('/shorts/')) {
      id = u.pathname.split('/').filter(Boolean)[1] ?? null;
    } else if (u.pathname.startsWith('/live/')) {
      id = u.pathname.split('/').filter(Boolean)[1] ?? null;
    } else if (u.pathname.startsWith('/embed/')) {
      id = u.pathname.split('/').filter(Boolean)[1] ?? null;
    } else {
      id = u.searchParams.get('v');
    }
    // Playlist-only links carry no single video.
    if (!id && u.searchParams.get('list')) {
      return {
        kind: 'YOUTUBE',
        provider: 'youtube',
        externalId: null,
        dedicated: true,
        permitted: false,
        reason: 'That link points at a playlist, not a single video. Paste one video URL.',
      };
    }
    return {
      kind: 'YOUTUBE',
      provider: 'youtube',
      externalId: id && /^[A-Za-z0-9_-]{6,}$/.test(id) ? id : null,
      dedicated: true,
      permitted: true,
    };
  }

  if (matches(host, TIKTOK_HOSTS)) {
    const parts = u.pathname.split('/').filter(Boolean);
    const idx = parts.findIndex((p) => p === 'video');
    const id = idx >= 0 ? (parts[idx + 1] ?? null) : null;
    return {
      kind: 'TIKTOK',
      provider: 'tiktok',
      externalId: id && /^\d+$/.test(id) ? id : null,
      dedicated: true,
      permitted: true,
    };
  }

  if (matches(host, FACEBOOK_HOSTS)) {
    // Group content is members-only: refuse it rather than trying to fetch it.
    if (u.pathname.includes('/groups/')) {
      return {
        kind: 'FACEBOOK',
        provider: 'facebook',
        externalId: null,
        dedicated: true,
        permitted: false,
        reason:
          'That is a Facebook group post. Group content is members-only, so ViralCut will not fetch it.',
      };
    }
    let id = u.searchParams.get('v') ?? u.searchParams.get('video_id') ?? u.searchParams.get('story_fbid');
    if (!id) {
      const parts = u.pathname.split('/').filter(Boolean);
      for (const marker of ['videos', 'watch']) {
        const idx = parts.indexOf(marker);
        if (idx >= 0 && parts[idx + 1] && /^\d+$/.test(parts[idx + 1])) {
          id = parts[idx + 1];
          break;
        }
      }
    }
    return {
      kind: 'FACEBOOK',
      provider: 'facebook',
      externalId: id,
      dedicated: true,
      permitted: true,
      reason:
        'Only public Facebook videos can be processed. Private or group-only posts are refused.',
    };
  }

  if (isPrivateHost(host)) {
    return {
      kind: 'GENERIC',
      provider: host,
      externalId: null,
      dedicated: false,
      permitted: false,
      reason: 'Internal and loopback addresses cannot be imported.',
    };
  }

  // Direct media files are handled by the generic provider.
  const isDirectMedia = /\.(mp4|mov|webm|mkv|m4v|mp3|m4a|wav|aac)(\?|$)/i.test(u.pathname + u.search);
  return {
    kind: 'GENERIC',
    provider: host || 'generic',
    externalId: null,
    dedicated: false,
    permitted: true,
    reason: isDirectMedia
      ? undefined
      : 'Generic import. ViralCut will only use publicly accessible media and will never bypass a login, paywall or DRM.',
  };
}

/**
 * Block loopback / RFC1918 / link-local hosts. The ingest worker runs inside the
 * VPC, so a pasted `http://localhost:…` or metadata-service URL would otherwise
 * become an SSRF vector.
 */
export function isPrivateHost(hostname: string): boolean {
  const host = hostname.toLowerCase().replace(/\.$/, '');
  if (!host) return false;
  if (host === 'localhost' || host === 'metadata.google.internal') return true;
  if (/^(127\.|10\.|192\.168\.|169\.254\.|0\.)/.test(host)) return true;
  const m = host.match(/^172\.(\d+)\./);
  if (m) {
    const second = Number(m[1]);
    if (second >= 16 && second <= 31) return true;
  }
  if (host.includes(':')) return host === '::1' || host === '[::1]' || host.toLowerCase().startsWith('fe80');
  return false;
}

/** Zod-friendly predicate: is this something we would even try to ingest? */
export function isProcessableUrl(rawUrl: string): boolean {
  return detectProvider(rawUrl).permitted;
}
