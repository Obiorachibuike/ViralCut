import { PrismaAdapter } from '@next-auth/prisma-adapter';
import { compare, hash } from 'bcryptjs';
import type { NextAuthOptions } from 'next-auth';
import CredentialsProvider from 'next-auth/providers/credentials';
import GoogleProvider from 'next-auth/providers/google';

import { prisma } from './db';

export const authOptions: NextAuthOptions = {
  adapter: PrismaAdapter(prisma as never),
  session: { strategy: 'jwt' },
  secret: process.env.NEXTAUTH_SECRET,
  pages: { signIn: '/login', error: '/login' },
  providers: [
    GoogleProvider({
      clientId: process.env.GOOGLE_CLIENT_ID ?? '',
      clientSecret: process.env.GOOGLE_CLIENT_SECRET ?? '',
      allowDangerousEmailAccountLinking: true,
    }),
    CredentialsProvider({
      name: 'Email and password',
      credentials: {
        email: { label: 'Email', type: 'email' },
        password: { label: 'Password', type: 'password' },
      },
      async authorize(credentials) {
        const email = credentials?.email?.toLowerCase().trim();
        const password = credentials?.password;
        if (!email || !password) return null;

        const user = await (prisma as any).user.findUnique({
          where: { email },
        });
        if (!user?.passwordHash) return null;

        const ok = await compare(password, user.passwordHash as string);
        if (!ok) return null;

        return { id: user.id, email: user.email, name: user.name, image: user.image };
      },
    }),
  ],
  callbacks: {
    async jwt({ token, user }) {
      if (user) token.sub = (user as { id: string }).id ?? token.sub;
      return token;
    },
    async session({ session, token }) {
      if (session.user) (session.user as { id?: string }).id = token.sub as string | undefined;
      return session;
    },
  },
};

/** Hash a plaintext password for the credentials provider. */
export function hashPassword(plain: string): Promise<string> {
  return hash(plain, 12);
}

export async function requireUserId(session: { user?: { id?: string } } | null): Promise<string> {
  const id = session?.user?.id;
  if (!id) throw new Error('unauthorized');
  return id;
}
