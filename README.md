# ViralCut — AI Video Moment Discovery & Short-Form Clipping Platform

> **Turn long videos into viral moments.** Upload a video or paste a public video URL.
> ViralCut analyzes the entire conversation and finds the moments people will actually
> want to watch.

ViralCut is a production-style monorepo: a **Next.js 15** application (auth, landing,
dashboard, upload, URL import, moment discovery UI, browser editor, text-to-video,
social publishing) and a **Python FastAPI media engine** that does every piece of real
video/AI work — FFmpeg, faster-whisper transcription, pyannote diarization, PySceneDetect
scene detection, an 8-dimension moment-scoring engine, reframing, captions, rendering and
text-to-video generation — coordinated through **Redis + BullMQ** jobs, **PostgreSQL +
Prisma + pgvector** storage and **Cloudflare R2** object storage.

Three ways to get video in, one way to get it out:

| Path | How |
|---|---|
| **Upload** | Drag-and-drop MP4/MOV/WebM/MKV/M4V, up to 10 GB |
| **URL import** | Public YouTube / TikTok / Facebook / direct links via `yt-dlp`, with DRM/private/login refused |
| **Text to video** | Describe a shot; a pluggable backend generates it, then it is treated as normal source footage |
| **Publish out** | One click from the editor to YouTube, TikTok, Facebook, Instagram, LinkedIn or X |

> **No fake processing.** Every stage calls real libraries against the real file. Where an
> optional dependency is missing (GPU Whisper, pyannote, an LLM key), that stage degrades
> gracefully and is reported honestly — it is never silently faked. Deterministic moment
> scoring always runs; an LLM only *augments* it when a key is configured.

---

## Architecture

```
                ┌─────────────────────────── Next.js (apps/web) ───────────────────────────┐
  Browser  ───► │  Landing · Auth · Dashboard · Upload · Moments UI · Editor                │
                │  API routes (Zod-validated) ── never run FFmpeg/AI in Node                │
                └───────┬───────────────────────────────┬───────────────────┬──────────────┘
                        │ enqueue (BullMQ)               │ HTTP (token)      │ SSE (live status)
                        ▼                                ▼                   ▲
                 ┌─────────────┐                 ┌──────────────────────┐    │
                 │   Redis     │                 │  FastAPI media engine │   │
                 │ (BullMQ +   │  workers ─────► │  apps/api (Python)    │───┘ callbacks
                 │  pub/sub)   │  (cpu / gpu)    │  FFmpeg · Whisper ·   │
                 └─────────────┘                 │  pyannote · scenes ·  │
                        │                        │  moments · render     │
                        ▼                        └──────────┬───────────┘
                 ┌─────────────┐                            │
                 │ PostgreSQL  │  Prisma + pgvector         ▼
                 │ (metadata)  │                   Cloudflare R2 / local storage
                 └─────────────┘                   (sources, audio, transcripts, clips)
```

**Pipeline** (Python `services/pipeline.py`): media inspection → audio extraction →
transcription → diarization → scene detection → moment discovery (deterministic scoring)
→ optional LLM refinement/hooks/titles → thumbnails + SRT/VTT → results persisted by the
Next.js worker.

---

## Monorepo layout

```
apps/
  web/        Next.js 15 (App Router, TS, Tailwind, shadcn-style UI, Framer Motion)
              app/api/*  REST routes · workers/ BullMQ + job handlers
  api/        FastAPI media engine (Python): providers, transcription, diarization,
              video (ffmpeg/reframe/captions/render), moments engine, ai, services
packages/
  shared/     provider detection, job/plan constants, Zod schemas (TS ⇄ Python parity)
  ai/         AIProvider abstraction + versioned prompt library (v1)
  database/   PrismaClient singleton
  config/     shared Tailwind preset / tsconfig
prisma/       schema.prisma (20 models incl. pgvector) + migration
infrastructure/docker/   Dockerfiles for web + media-engine
```

---

## Prerequisites

- **Node 20+**, **Python 3.11+**
- **PostgreSQL 16** with the `pgvector` extension
- **Redis 7**
- **FFmpeg 6+** (with `libx264`, `libass`, `aac`) and `ffprobe` on `PATH`
- Optional: a CUDA GPU for faster Whisper; a Hugging Face token for pyannote; an
  OpenAI-compatible API key for LLM augmentation.

---

## Install & run (local)

```bash
# 1. Install JS deps (npm workspaces)
npm install

# 2. Configure environment
cp .env.example .env        # fill in DATABASE_URL, REDIS_URL, secrets, R2, AI key

# 3. Database
npm run db:generate         # generates the Prisma client (needs DATABASE_URL)
npm run db:migrate          # applies prisma/migrations (creates pgvector + tables)

# 4. Python media engine
python3 -m pip install -r apps/api/requirements.txt
# (optional GPU) pip install faster-whisper[cuda]; export PYANNOTE_HF_TOKEN=...

# 5. Start everything (three terminals)
npm run dev:api             # FastAPI on :8000
npm run dev:worker          # BullMQ workers (or inline driver if REDIS_URL unset)
npm run dev:web             # Next.js on :3000
```

Open http://localhost:3000.

---

## Environment variables

See [`.env.example`](./.env.example) for the full, annotated list. Key groups:

| Group | Variables |
|---|---|
| Database | `DATABASE_URL` |
| Queue | `REDIS_URL`, `QUEUE_DRIVER` (`redis`\|`inline`) |
| Auth | `NEXTAUTH_SECRET`, `NEXTAUTH_URL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` |
| Storage (R2) | `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`, `R2_PUBLIC_URL` |
| AI | `AI_API_KEY`, `VIRALCUT_AI_PROVIDER`, `VIRALCUT_AI_MODEL`, `VIRALCUT_AI_BASE_URL` |
| Engine bridge | `FASTAPI_URL`, `MEDIA_ENGINE_TOKEN`, `VIRALCUT_CALLBACK_BASE_URL`, `VIRALCUT_CALLBACK_TOKEN` |
| Media | `FFMPEG_PATH`, `MEDIA_WORK_DIR`, `WHISPER_DEVICE`, `PYANNOTE_HF_TOKEN` |
| LongCat (optional) | `LONGCAT_ENABLED`, `LONGCAT_API_URL`, `LONGCAT_WORKER_TOKEN` |

> No secret is ever sent to the browser. The media engine is reachable only with
> `MEDIA_ENGINE_TOKEN`; callbacks only with `VIRALCUT_CALLBACK_TOKEN`.

---

## FFmpeg / Whisper / pyannote / workers

- **FFmpeg** does inspection, audio extraction, cutting, reframing, caption burn-in
  (via `libass`), audio mixing and rendering. Captions use libass (works with or without
  `drawtext`).
- **faster-whisper** provides word + segment timestamps. `WHISPER_DEVICE=cpu` with
  `int8` works without a GPU; set `cuda` when available.
- **pyannote** provides speaker diarization and needs `PYANNOTE_HF_TOKEN`; when absent the
  diarization stage is skipped and reported, and clips fall back to center/auto framing.
- **Workers**: `apps/web/workers` runs BullMQ consumers for the `cpu` and `gpu` queues.
  For single-process development, set no `REDIS_URL` and the **inline** driver runs the
  same handlers in-process.

---

## LongCat-Video (optional GPU worker)

LongCat-Video is an **independent, optional** worker for AI B-roll, image-to-video and
transitions. It is toggled by `LONGCAT_ENABLED` and **never required** for normal
clipping — if it is unavailable the app continues to work and B-roll generation is simply
skipped.

---

## Production architecture & deployment

- **Stateless web** (Next.js) behind a load balancer; **separate worker** processes;
  **media engine** horizontally scalable behind the queue; **Postgres** (managed) +
  **Redis** (managed) + **R2**.
- `docker-compose.yml` wires `postgres` (pgvector), `redis`, `media-engine`, `web` and
  `worker`. Build images from `infrastructure/docker/*`.
- Long videos never block HTTP requests: uploads/imports enqueue jobs; the browser watches
  progress over **SSE** (`/api/jobs/[id]/stream`), not 1s polling.

---

## Text to video

`apps/api/generation` implements one `TextToVideoProvider` contract with five backends:

| Provider | `VIRALCUT_T2V_PROVIDER` | Credential |
|---|---|---|
| LongCat-Video (self-hosted GPU) | `longcat` | `LONGCAT_ENABLED`, `LONGCAT_API_URL` |
| fal.ai | `fal` | `FAL_KEY` |
| Replicate | `replicate` | `REPLICATE_API_TOKEN` + `VIRALCUT_T2V_MODEL` |
| Luma Dream Machine | `luma` | `LUMA_API_KEY` |
| Runway | `runway` | `RUNWAY_API_KEY` |

Flow: `POST /api/generate` creates a `Project` + `Video` shell and queues
`generate-text-to-video`; the worker calls the engine's `POST /v1/generate/text-to-video`,
which generates, downloads the result, probes it with FFmpeg, stores it under
`generated/{runId}/source.mp4` and thumbnails it. The `Video` row is then updated and
`analyze-video` runs, so generated footage goes through the exact same moment-discovery
and clipping path as an upload.

With `VIRALCUT_T2V_PROVIDER=none` the `/generate` page states plainly that no backend is
active and lists what each one needs. It never pretends to generate.

## Social publishing

`apps/web/lib/publishing` holds one adapter per network behind a `SocialPublisher`
interface. Each is `configured()` only when its OAuth app credentials exist, so the
Settings page can show exactly what is missing.

| Platform | What you must create | Required env |
|---|---|---|
| **YouTube** | Google Cloud OAuth client + YouTube Data API v3 enabled | `YOUTUBE_CLIENT_ID/SECRET` (or `GOOGLE_*`) |
| **TikTok** | Developer app with the **Content Posting API** product; public posting requires passing TikTok's audit | `TIKTOK_CLIENT_KEY/SECRET` |
| **Facebook** | Meta app with `pages_manage_posts` + `publish_video` approved; a Page you manage | `FACEBOOK_CLIENT_ID/SECRET` |
| **Instagram** | Same Meta app + `instagram_content_publish`; a Page linked to a **Business or Creator** Instagram account, and a public URL for the video (R2 with a public base URL) | `FACEBOOK_CLIENT_ID/SECRET` |
| **LinkedIn** | App with "Share on LinkedIn" + "Sign In with LinkedIn using OpenID Connect" | `LINKEDIN_CLIENT_ID/SECRET` |
| **X** | App with OAuth 2.0 user context (PKCE) enabled | `X_CLIENT_ID/SECRET` |

Behaviour worth knowing:

- **Tokens are encrypted at rest** (AES-256-GCM, key from `SOCIAL_TOKEN_KEY`) and are never
  returned to the browser. They are decrypted only inside the worker performing an upload.
- **OAuth is CSRF-protected**: a signed state cookie must match on callback (constant-time
  compare), and X's PKCE verifier is carried in that same cookie.
- **Platform differences are surfaced, not hidden.** TikTok has no unlisted state (it maps
  to "only me"), and Instagram publishes publicly or not at all — the adapter refuses an
  unsupported visibility with a readable message rather than silently changing your intent.
- **An expired token marks the account `EXPIRED`** instead of being retried forever.
- Instagram is the only platform that requires a publicly reachable video URL, because it
  pulls the file server-side.

> These integrations are implemented against each vendor's documented API. They cannot be
> exercised from this repository's sandbox (no outbound access to those hosts, and no
> developer-app credentials), so the first real upload must be verified in an environment
> that has them. The adapter pre-flight guards, token encryption and OAuth URL construction
> are covered by `npx vitest run`.

## Troubleshooting

- **`PrismaClient did not initialize`** — run `npm run db:generate` (needs `DATABASE_URL`).
- **`ffmpeg: not found`** in `/v1/health` — install FFmpeg and set `FFMPEG_PATH`.
- **URL import refused** — private, login-gated, DRM-protected, paid and live sources are
  rejected by design; we never bypass authentication, DRM or paywalls.
- **No moments** — a video with no detectable speech yields zero candidates (honest
  result); check the transcript stage in the run log.
- **`yt-dlp is not installed`** on URL import — `pip install yt-dlp` in the media engine.
- **Platform shows "needs setup"** — that network's OAuth credentials are not in `.env`;
  the Settings page prints the exact steps for it.
- **`Instagram ... requires a public URL`** — set `R2_PUBLIC_URL` (or another public base
  URL) so Instagram can pull the clip server-side.

---

## Tests

```bash
cd apps/api && python3 -m pytest -q      # 176 tests: providers, moments, video/render, pipeline, generation, storage
npx vitest run                            # 23 tests: token crypto, OAuth URLs, adapter registry + guards
npm run build                             # Next.js typecheck + production build
npm run db:validate                       # Prisma schema via prisma-fmt WASM
```

The Python suite includes **real FFmpeg pipeline and render integration tests** (probe →
audio → scenes → moments → thumbnails → a burned-in vertical clip), plus provider-detection
parity with the TypeScript classifier.

---

© ViralCut. You own everything you create.
