import { z } from 'zod';
import {
  ACCEPTED_EXTENSIONS,
  ASPECT_RATIOS,
  CAPTION_STYLES,
  MAX_UPLOAD_BYTES,
  MOMENT_CATEGORIES,
  REFRAME_MODES,
  SCORING_DIMENSIONS,
} from './constants';

export const urlSchema = z
  .string()
  .trim()
  .min(8, 'Paste a full video URL, e.g. https://www.youtube.com/watch?v=…')
  .max(2048)
  .refine((v) => /^https?:\/\//i.test(v), 'URL must start with http:// or https://');

export const scoringWeightsSchema = z
  .object(Object.fromEntries(SCORING_DIMENSIONS.map((d) => [d, z.number().min(0).max(1).optional()])) as Record<
    (typeof SCORING_DIMENSIONS)[number],
    z.ZodOptional<z.ZodNumber>
  >)
  .partial()
  .refine((w) => Object.values(w).every((v) => v === undefined || (v >= 0 && v <= 1)), {
    message: 'Each scoring weight must be between 0 and 1.',
  });

export const analyzeRequestSchema = z.object({
  /** Cap on generated candidate moments. Defaults scale with duration. */
  maxCandidates: z.number().int().min(5).max(200).optional(),
  /** Minimum final score (0-100) required to keep a moment. */
  minScore: z.number().min(0).max(100).optional(),
  minDurationSec: z.number().min(5).max(600).optional(),
  maxDurationSec: z.number().min(10).max(900).optional(),
  categories: z.array(z.enum(MOMENT_CATEGORIES)).optional(),
  padBeforeSec: z.number().min(0).max(5).optional(),
  padAfterSec: z.number().min(0).max(5).optional(),
  scoringWeights: scoringWeightsSchema.optional(),
  /** Force a specific AI provider instead of the configured default. */
  provider: z.string().optional(),
  /** Re-run even if a completed analysis already exists. */
  force: z.boolean().optional(),
});

export const generateMomentSchema = z.object({
  momentId: z.string().min(1),
  aspectRatio: z.enum(['9:16', '1:1', '16:9', '4:5']).optional(),
  reframeMode: z.enum(REFRAME_MODES).optional(),
  captionStyle: z.enum(CAPTION_STYLES).optional(),
  title: z.string().max(160).optional(),
  hook: z.string().max(500).optional(),
});

export const batchGenerateSchema = z.object({
  momentIds: z.array(z.string().min(1)).min(1).max(50),
  aspectRatio: z.enum(['9:16', '1:1', '16:9', '4:5']).optional(),
  captionStyle: z.enum(CAPTION_STYLES).optional(),
  reframeMode: z.enum(REFRAME_MODES).optional(),
});

export const createClipSchema = z.object({
  videoId: z.string().min(1),
  momentId: z.string().optional(),
  startMs: z.number().int().min(0),
  endMs: z.number().int().min(1),
  title: z.string().min(1).max(160),
  aspectRatio: z.enum(['9:16', '1:1', '16:9', '4:5']).default('9:16'),
  captionStyle: z.enum(CAPTION_STYLES).default('CREATOR'),
  reframeMode: z.enum(REFRAME_MODES).default('AUTO'),
});

export const patchClipSchema = z
  .object({
    title: z.string().min(1).max(160).optional(),
    hook: z.string().max(500).nullable().optional(),
    trimStartMs: z.number().int().min(0).optional(),
    trimEndMs: z.number().int().min(0).nullable().optional(),
    aspectRatio: z.enum(Object.keys(ASPECT_RATIOS) as ['9:16', '1:1', '16:9', '4:5']).optional(),
    reframeMode: z.enum(REFRAME_MODES).optional(),
    captionStyle: z.enum(CAPTION_STYLES).optional(),
    captionFont: z.string().max(80).optional(),
    captionSize: z.number().int().min(24).max(160).optional(),
    captionPositionY: z.number().min(0).max(1).optional(),
    captionUppercase: z.boolean().optional(),
    captionHighlightWords: z.array(z.string().max(40)).max(40).optional(),
    captionPrimaryColor: z.string().regex(/^#[0-9a-fA-F]{6}$/).optional(),
    captionAccentColor: z.string().regex(/^#[0-9a-fA-F]{6}$/).optional(),
    captionBackground: z.string().regex(/^#[0-9a-fA-F]{6}$/).nullable().optional(),
    captionAnimation: z.boolean().optional(),
    muted: z.boolean().optional(),
    volume: z.number().min(0).max(3).optional(),
    musicVolume: z.number().min(0).max(1).optional(),
    watermarkText: z.string().max(60).nullable().optional(),
    captions: z
      .array(
        z.object({
          index: z.number().int().min(0),
          startMs: z.number().int().min(0),
          endMs: z.number().int().min(0),
          text: z.string(),
        }),
      )
      .optional(),
  })
  .refine((v) => v.trimEndMs === undefined || v.trimEndMs === null || v.trimEndMs > (v.trimStartMs ?? 0), {
    message: 'trimEndMs must be greater than trimStartMs',
  });

export const renderRequestSchema = z.object({
  platform: z.enum(['TIKTOK', 'YOUTUBE_SHORTS', 'INSTAGRAM_REELS', 'YOUTUBE', 'LINKEDIN', 'CUSTOM']).optional(),
  /** Cap the render height — plan limits clamp this server-side. */
  maxHeight: z.number().int().min(240).max(2160).optional(),
  watermark: z.boolean().optional(),
});

export const uploadFileSchema = z.object({
  filename: z.string().min(1).max(255),
  size: z.number().int().positive().max(MAX_UPLOAD_BYTES),
  type: z.string().min(1),
});

export const uploadChunkSchema = z.object({
  uploadId: z.string().min(1),
  index: z.number().int().min(0),
  total: z.number().int().min(1),
  filename: z.string().min(1).max(255),
  size: z.number().int().positive(),
});

export const uploadCompleteSchema = z.object({
  uploadId: z.string().min(1),
  filename: z
    .string()
    .min(1)
    .max(255)
    .refine(
      (f) => ACCEPTED_EXTENSIONS.some((ext) => f.toLowerCase().endsWith(ext)),
      `Unsupported file type. Supported: ${ACCEPTED_EXTENSIONS.join(', ')}`,
    ),
  size: z.number().int().positive().max(MAX_UPLOAD_BYTES),
  type: z.string().optional(),
  projectId: z.string().optional(),
  title: z.string().max(200).optional(),
});

export const importUrlSchema = z.object({
  url: urlSchema,
  projectId: z.string().optional(),
  title: z.string().max(200).optional(),
  /** Start the pipeline immediately after ingestion (default true). */
  analyze: z.boolean().optional(),
});

export const createProjectSchema = z.object({
  name: z.string().min(1).max(120),
  description: z.string().max(1000).optional(),
});

export const registerSchema = z.object({
  email: z.string().email(),
  password: z.string().min(8, 'Use at least 8 characters.').max(200),
  name: z.string().min(1).max(120).optional(),
});

export const loginSchema = z.object({
  email: z.string().email(),
  password: z.string().min(1),
});

export const momentsQuerySchema = z.object({
  category: z.enum(['ALL', ...MOMENT_CATEGORIES]).optional(),
  minScore: z.coerce.number().min(0).max(100).optional(),
  limit: z.coerce.number().int().min(1).max(200).optional(),
  includeDuplicates: z.coerce.boolean().optional(),
});

export type AnalyzeRequest = z.infer<typeof analyzeRequestSchema>;
export type ImportUrlInput = z.infer<typeof importUrlSchema>;
export type PatchClipInput = z.infer<typeof patchClipSchema>;
export type CreateClipInput = z.infer<typeof createClipSchema>;
