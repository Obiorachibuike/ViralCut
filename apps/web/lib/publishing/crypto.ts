/**
 * At-rest encryption for platform tokens.
 *
 * Access/refresh tokens are credentials: they let us post as the user. They are
 * encrypted with AES-256-GCM before they reach the database and decrypted only
 * inside the worker that performs an upload. They are never returned to the
 * browser — the accounts endpoint strips them.
 *
 * The key is derived from SOCIAL_TOKEN_KEY (or NEXTAUTH_SECRET as a fallback) so
 * a deployment does not need a second secret to be secure, but setting a
 * dedicated key is recommended.
 */
import {
  createCipheriv,
  createDecipheriv,
  createHash,
  createHmac,
  randomBytes,
  timingSafeEqual,
} from 'node:crypto';

const ALGO = 'aes-256-gcm';

function keyMaterial(): Buffer {
  const secret = process.env.SOCIAL_TOKEN_KEY ?? process.env.NEXTAUTH_SECRET;
  if (!secret) {
    throw new Error(
      'Token encryption needs SOCIAL_TOKEN_KEY (or NEXTAUTH_SECRET) to be set.',
    );
  }
  return createHash('sha256').update(secret).digest();
}

export function encryptToken(plaintext: string): string {
  const iv = randomBytes(12);
  const cipher = createCipheriv(ALGO, keyMaterial(), iv);
  const enc = Buffer.concat([cipher.update(plaintext, 'utf8'), cipher.final()]);
  const tag = cipher.getAuthTag();
  return `v1.${iv.toString('base64')}.${tag.toString('base64')}.${enc.toString('base64')}`;
}

export function decryptToken(payload: string): string {
  const parts = payload.split('.');
  if (parts.length !== 4 || parts[0] !== 'v1') {
    throw new Error('Malformed encrypted token');
  }
  const [, iv, tag, data] = parts;
  const decipher = createDecipheriv(ALGO, keyMaterial(), Buffer.from(iv, 'base64'));
  decipher.setAuthTag(Buffer.from(tag, 'base64'));
  return Buffer.concat([decipher.update(Buffer.from(data, 'base64')), decipher.final()]).toString(
    'utf8',
  );
}

/** Constant-time comparison for callback state tokens. */
export function safeEqual(a: string, b: string): boolean {
  const ha = createHmac('sha256', keyMaterial()).update(a).digest();
  const hb = createHmac('sha256', keyMaterial()).update(b).digest();
  return timingSafeEqual(ha, hb);
}
