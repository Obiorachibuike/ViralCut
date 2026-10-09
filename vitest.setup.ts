/**
 * Test environment. The OAuth config and token encryption read env vars at
 * module load, so they must exist before any publishing module is imported.
 */
process.env.NEXTAUTH_SECRET = 'test-secret-for-token-encryption';
process.env.SOCIAL_TOKEN_KEY = 'test-social-token-key';
process.env.FACEBOOK_CLIENT_ID = 'fb-test-client';
process.env.FACEBOOK_CLIENT_SECRET = 'fb-test-secret';
process.env.X_CLIENT_ID = 'x-test-client';
process.env.X_CLIENT_SECRET = 'x-test-secret';
// Deliberately left unset so the "not configured" paths stay covered:
// YOUTUBE_CLIENT_ID, TIKTOK_CLIENT_KEY, LINKEDIN_CLIENT_ID
