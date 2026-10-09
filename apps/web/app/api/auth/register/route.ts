import { hash } from 'bcryptjs';
import { NextResponse } from 'next/server';

import { prisma } from '@/lib/db';

export async function POST(request: Request) {
  const body = await request.json().catch(() => ({}));
  const email = typeof body?.email === 'string' ? body.email.toLowerCase().trim() : '';
  const name = typeof body?.name === 'string' ? body.name.trim() : null;
  const password = typeof body?.password === 'string' ? body.password : '';

  if (!email || !/^\S+@\S+\.\S+$/.test(email)) {
    return NextResponse.json({ error: 'A valid email is required' }, { status: 400 });
  }
  if (password.length < 8) {
    return NextResponse.json({ error: 'Password must be at least 8 characters' }, { status: 400 });
  }

  const existing = await (prisma as any).user.findUnique({ where: { email } });
  if (existing) return NextResponse.json({ error: 'An account with that email already exists' }, { status: 409 });

  const passwordHash = await hash(password, 12);
  const user = await (prisma as any).user.create({
    data: { email, name, passwordHash },
  });

  return NextResponse.json({ id: user.id, email: user.email });
}
