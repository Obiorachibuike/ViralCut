/**
 * Publishing layer tests.
 *
 * These exercise the parts that are pure logic: token encryption, OAuth URL
 * construction, the adapter registry, and each adapter's pre-flight guards.
 * The guards matter because they are what turns a misconfiguration into a
 * readable message instead of a failed upload three minutes in.
 */
import { beforeAll, describe, expect, it } from 'vitest';

import { decryptToken, encryptToken, safeEqual } from './crypto';
import { describePlatforms, getPublisher, isPlatform } from './index';
import { buildAuthorizeUrl, expiresInDate, OAUTH } from './oauth';
import { PublishError } from './types';

beforeAll(() => {
  process.env.NEXTAUTH_SECRET = 'test-secret-for-token-encryption';
});

describe('token encryption', () => {
  it('round-trips a token', () => {
    const token = 'ya29.a0AfH6SMBx-real-looking-token';
    expect(decryptToken(encryptToken(token))).toBe(token);
  });

  it('produces a fresh ciphertext each time (random IV)', () => {
    const a = encryptToken('same');
    const b = encryptToken('same');
    expect(a).not.toBe(b);
    expect(decryptToken(a)).toBe(decryptToken(b));
  });

  it('rejects a tampered payload', () => {
    const sealed = encryptToken('secret');
    const [, iv, tag, data] = sealed.split('.');
    const flipped = Buffer.from(data, 'base64');
    flipped[0] ^= 0xff;
    expect(() => decryptToken(`v1.${iv}.${tag}.${flipped.toString('base64')}`)).toThrow();
  });

  it('rejects a malformed payload', () => {
    expect(() => decryptToken('not-a-token')).toThrow(/Malformed/);
  });

  it('compares state tokens without leaking timing', () => {
    expect(safeEqual('abc', 'abc')).toBe(true);
    expect(safeEqual('abc', 'abd')).toBe(false);
  });
});

describe('oauth url construction', () => {
  it('builds an authorize url with client id, state, redirect and scopes', () => {
    // Facebook is configured by vitest.setup.ts, so this exercises the real builder.
    const url = buildAuthorizeUrl('FACEBOOK', 'state-1', 'https://app.test/cb');
    expect(url).toContain('client_id=fb-test-client');
    expect(url).toContain('state=state-1');
    expect(url).toContain('redirect_uri=https%3A%2F%2Fapp.test%2Fcb');
    expect(url).toContain('response_type=code');
    expect(url).toContain('pages_manage_posts');
    expect(url).toContain('publish_video');
  });

  it('refuses to build a url for a platform with no credentials', () => {
    expect(() => buildAuthorizeUrl('TIKTOK', 's', 'https://app.test/cb')).toThrow(
      /not configured/i,
    );
  });

  it('adds PKCE parameters only when the platform requires them', () => {
    expect(OAUTH.X.pkce).toBe(true);
    expect(OAUTH.YOUTUBE.pkce).toBeUndefined();

    const withPkce = buildAuthorizeUrl('X', 's', 'https://app.test/cb', 'challenge-123');
    expect(withPkce).toContain('code_challenge=challenge-123');
    expect(withPkce).toContain('code_challenge_method=S256');

    const without = buildAuthorizeUrl('X', 's', 'https://app.test/cb');
    expect(without).not.toContain('code_challenge');
  });

  it('computes an expiry that lands before the real one', () => {
    const at = expiresInDate(3600);
    expect(at).not.toBeNull();
    const msLeft = at!.getTime() - Date.now();
    // 60s safety margin, so between 58 and 60 minutes.
    expect(msLeft).toBeGreaterThan(58 * 60_000);
    expect(msLeft).toBeLessThanOrEqual(59 * 60_000 + 5000);
  });

  it('returns null when no expiry was given', () => {
    expect(expiresInDate(undefined)).toBeNull();
  });
});

describe('adapter registry', () => {
  it('knows all six platforms', () => {
    const platforms = describePlatforms().map((p) => p.platform);
    expect(platforms).toEqual(['YOUTUBE', 'TIKTOK', 'FACEBOOK', 'INSTAGRAM', 'LINKEDIN', 'X']);
  });

  it('explains what is missing when a platform is not configured', () => {
    for (const entry of describePlatforms()) {
      const publisher = getPublisher(entry.platform);
      if (!publisher.configured()) {
        expect(entry.setupHint, `${entry.platform} should explain its setup`).toBeTruthy();
        expect(entry.setupHint!.length).toBeGreaterThan(20);
      }
    }
  });

  it('validates platform names case-insensitively', () => {
    expect(isPlatform('youtube')).toBe(true);
    expect(isPlatform('TIKTOK')).toBe(true);
    expect(isPlatform('myspace')).toBe(false);
  });

  it('rejects an unknown platform', () => {
    // isPlatform guards callers, so this is the defensive path.
    expect(() => getPublisher('MYSPACE' as never)).toThrow(PublishError);
  });

  it('gives every adapter a label and a publish implementation', () => {
    for (const platform of ['YOUTUBE', 'TIKTOK', 'FACEBOOK', 'INSTAGRAM', 'LINKEDIN', 'X'] as const) {
      const publisher = getPublisher(platform);
      expect(publisher.label).toBeTruthy();
      expect(typeof publisher.publish).toBe('function');
      expect(typeof publisher.connect).toBe('function');
      expect(typeof publisher.authorizeUrl).toBe('function');
    }
  });
});

describe('adapter pre-flight guards', () => {
  const token = { accessToken: 'test' };

  it('YouTube refuses without a local file', async () => {
    await expect(
      getPublisher('YOUTUBE').publish(token, { title: 't', privacy: 'PUBLIC' }, {}),
    ).rejects.toMatchObject({ opts: { code: 'missing_file' } });
  });

  it('LinkedIn refuses without a local file', async () => {
    await expect(
      getPublisher('LINKEDIN').publish(token, { title: 't', privacy: 'PUBLIC' }, {}),
    ).rejects.toMatchObject({ opts: { code: 'missing_file' } });
  });

  it('X refuses without a local file', async () => {
    await expect(
      getPublisher('X').publish(token, { title: 't', privacy: 'PUBLIC' }, {}),
    ).rejects.toMatchObject({ opts: { code: 'missing_file' } });
  });

  it('TikTok refuses with neither file nor url', async () => {
    await expect(
      getPublisher('TIKTOK').publish(token, { title: 't', privacy: 'PUBLIC' }, {}),
    ).rejects.toMatchObject({ opts: { code: 'missing_material' } });
  });

  it('Instagram refuses non-public visibility instead of silently posting', async () => {
    await expect(
      getPublisher('INSTAGRAM').publish(
        token,
        { title: 't', privacy: 'UNLISTED' },
        { fileUrl: 'https://cdn.test/clip.mp4' },
      ),
    ).rejects.toMatchObject({ opts: { code: 'privacy_unsupported' } });
  });

  it('Instagram refuses without a public url', async () => {
    await expect(
      getPublisher('INSTAGRAM').publish(token, { title: 't', privacy: 'PUBLIC' }, { filePath: '/tmp/x.mp4' }),
    ).rejects.toMatchObject({ opts: { code: 'requires_public_url' } });
  });

  it('Facebook refuses without the page id the worker injects', async () => {
    await expect(
      getPublisher('FACEBOOK').publish(
        token,
        { title: 't', privacy: 'PUBLIC' },
        { fileUrl: 'https://cdn.test/clip.mp4' },
      ),
    ).rejects.toMatchObject({ opts: { code: 'missing_page' } });
  });

  it('X connect refuses without the PKCE verifier', async () => {
    await expect(getPublisher('X').connect('code', 'https://app.test/cb', {})).rejects.toMatchObject({
      opts: { code: 'missing_verifier' },
    });
  });
});
