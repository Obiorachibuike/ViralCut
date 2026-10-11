/**
 * Shared constants used by both the Next.js app and (as the source of truth for
 * the wire contract) the FastAPI backend.
 */

export const JOB_STATES = [
  'QUEUED',
  'DOWNLOADING',
  'PROCESSING',
  'TRANSCRIBING',
  'ANALYZING',
  'FINDING_MOMENTS',
  'GENERATING_CLIPS',
  'RENDERING',
  'COMPLETED',
  'FAILED',
] as const;
export type JobState = (typeof JOB_STATES)[number];

export const JOB_TYPES = [
  'INGEST_VIDEO',
  'EXTRACT_AUDIO',
  'TRANSCRIBE_VIDEO',
  'DIARIZE_SPEAKERS',
  'DETECT_SCENES',
  'ANALYZE_TRANSCRIPT',
  'GENERATE_MOMENTS',
  'RANK_MOMENTS',
  'GENERATE_CLIP',
  'TRACK_FACES',
  'RENDER_VIDEO',
  'GENERATE_BROLL',
  'CLEANUP',
] as const;
export type JobType = (typeof JOB_TYPES)[number];

/** Queue names. CPU-bound work never shares a queue with GPU-bound work. */
export const QUEUES = {
  cpu: 'viralcut:cpu',
  gpu: 'viralcut:gpu',
  longcat: 'viralcut:longcat',
} as const;

export const VIDEO_STATUSES = [
  'PENDING',
  'UPLOADING',
  'UPLOADED',
  'PREPARING',
  'TRANSCRIBING',
  'DIARIZING',
  'SCENE_DETECTING',
  'ANALYZING',
  'FINDING_MOMENTS',
  'READY',
  'FAILED',
] as const;
export type VideoStatus = (typeof VIDEO_STATUSES)[number];

/** Ordered pipeline stages used to render the progress rail in the UI. */
export const PIPELINE_STAGES = [
  { id: 'UPLOADED', label: 'Uploaded' },
  { id: 'PREPARING', label: 'Preparing' },
  { id: 'TRANSCRIBING', label: 'Transcribing' },
  { id: 'DIARIZING', label: 'Detecting speakers' },
  { id: 'SCENE_DETECTING', label: 'Detecting scenes' },
  { id: 'ANALYZING', label: 'Analyzing' },
  { id: 'FINDING_MOMENTS', label: 'Finding moments' },
  { id: 'READY', label: 'Ready' },
] as const;

export const MOMENT_CATEGORIES = [
  'HOOK',
  'EMOTIONAL',
  'STORY',
  'EDUCATIONAL',
  'CONTROVERSIAL',
  'INSPIRATIONAL',
  'BUSINESS',
  'TECHNICAL',
  'SURPRISING',
  'FUNNY',
] as const;
export type MomentCategory = (typeof MOMENT_CATEGORIES)[number];

export const CATEGORY_FILTERS: { id: MomentCategory | 'ALL'; label: string }[] = [
  { id: 'ALL', label: 'All' },
  { id: 'FUNNY', label: 'Funny' },
  { id: 'EMOTIONAL', label: 'Emotional' },
  { id: 'EDUCATIONAL', label: 'Educational' },
  { id: 'CONTROVERSIAL', label: 'Controversial' },
  { id: 'INSPIRATIONAL', label: 'Inspirational' },
  { id: 'STORY', label: 'Story' },
  { id: 'BUSINESS', label: 'Business' },
  { id: 'TECHNICAL', label: 'Technical' },
  { id: 'SURPRISING', label: 'Surprising' },
];

export const SCORING_DIMENSIONS = [
  'hook',
  'curiosity',
  'emotion',
  'story',
  'value',
  'share',
  'standalone',
  'visual',
] as const;
export type ScoringDimension = (typeof SCORING_DIMENSIONS)[number];

/**
 * Default viral-score weights. Configurable per-project via `Project.scoreWeights`
 * and per-request via `scoringWeights` in the analyze payload.
 */
export const DEFAULT_SCORE_WEIGHTS: Record<ScoringDimension, number> = {
  hook: 0.2,
  curiosity: 0.15,
  emotion: 0.15,
  story: 0.15,
  value: 0.15,
  share: 0.1,
  standalone: 0.05,
  visual: 0.05,
};

export type AspectRatioId = '9:16' | '1:1' | '16:9' | '4:5';

export const ASPECT_RATIOS: Record<
  AspectRatioId,
  { id: AspectRatioId; label: string; width: number; height: number }
> = {
  '9:16': { id: '9:16', label: '9:16 Vertical', width: 1080, height: 1920 },
  '1:1': { id: '1:1', label: '1:1 Square', width: 1080, height: 1080 },
  '16:9': { id: '16:9', label: '16:9 Landscape', width: 1920, height: 1080 },
  '4:5': { id: '4:5', label: '4:5 Portrait', width: 1080, height: 1350 },
};

export type PresetId = 'TIKTOK' | 'INSTAGRAM_REELS' | 'YOUTUBE_SHORTS' | 'YOUTUBE' | 'LINKEDIN';

export const PLATFORM_PRESETS: Record<
  PresetId,
  { id: PresetId; label: string; ratio: AspectRatioId; maxSeconds: number; maxResolution: string }
> = {
  TIKTOK: { id: 'TIKTOK', label: 'TikTok', ratio: '9:16', maxSeconds: 180, maxResolution: '1080x1920' },
  INSTAGRAM_REELS: { id: 'INSTAGRAM_REELS', label: 'Instagram Reels', ratio: '9:16', maxSeconds: 90, maxResolution: '1080x1920' },
  YOUTUBE_SHORTS: { id: 'YOUTUBE_SHORTS', label: 'YouTube Shorts', ratio: '9:16', maxSeconds: 180, maxResolution: '1080x1920' },
  YOUTUBE: { id: 'YOUTUBE', label: 'YouTube', ratio: '16:9', maxSeconds: 43200, maxResolution: '3840x2160' },
  LINKEDIN: { id: 'LINKEDIN', label: 'LinkedIn', ratio: '1:1', maxSeconds: 600, maxResolution: '1920x1920' },
};

export const CAPTION_STYLES = [
  'MINIMAL',
  'BOLD',
  'KARAOKE',
  'CREATOR',
  'PODCAST',
  'HIGH_IMPACT',
] as const;
export type CaptionStyle = (typeof CAPTION_STYLES)[number];

export const REFRAME_MODES = ['AUTO', 'CENTER', 'SPEAKER_TRACK', 'SPLIT_SCREEN'] as const;
export type ReframeMode = (typeof REFRAME_MODES)[number];

export const SOURCE_KINDS = ['UPLOAD', 'YOUTUBE', 'TIKTOK', 'FACEBOOK', 'GENERIC'] as const;
export type SourceKind = (typeof SOURCE_KINDS)[number];

/** Accepted upload extensions and their MIME types (validated server-side). */
export const ACCEPTED_UPLOAD_TYPES: Record<string, string[]> = {
  'video/mp4': ['.mp4', '.m4v'],
  'video/quicktime': ['.mov'],
  'video/webm': ['.webm'],
  'video/x-matroska': ['.mkv'],
  'video/x-m4v': ['.m4v'],
};
export const ACCEPTED_EXTENSIONS = ['.mp4', '.mov', '.webm', '.mkv', '.m4v'];
export const MAX_UPLOAD_BYTES = 8 * 1024 * 1024 * 1024; // 8 GB
export const UPLOAD_CHUNK_BYTES = 8 * 1024 * 1024; // 8 MB chunks

export const PLAN_TIERS = ['FREE', 'CREATOR', 'PRO'] as const;
export type PlanTier = (typeof PLAN_TIERS)[number];

export interface PlanLimits {
  tier: PlanTier;
  label: string;
  videosPerMonth: number | null;
  clipMinutesPerMonth: number | null;
  maxExportHeight: number;
  watermark: boolean;
  aiBroll: boolean;
  priorityProcessing: boolean;
  priceMonthlyUsd: number;
  blurb: string;
  features: string[];
}

export const PLANS: PlanLimits[] = [
  {
    tier: 'FREE',
    label: 'Free',
    videosPerMonth: 3,
    clipMinutesPerMonth: 30,
    maxExportHeight: 720,
    watermark: true,
    aiBroll: false,
    priorityProcessing: false,
    priceMonthlyUsd: 0,
    blurb: 'Try the full pipeline on a few videos.',
    features: [
      '3 videos / month',
      '720p exports with watermark',
      'Up to 5 clips per video',
      'AI moment discovery & ranking',
      'Word-level captions',
    ],
  },
  {
    tier: 'CREATOR',
    label: 'Creator',
    videosPerMonth: 30,
    clipMinutesPerMonth: 600,
    maxExportHeight: 1080,
    watermark: false,
    aiBroll: false,
    priorityProcessing: false,
    priceMonthlyUsd: 29,
    blurb: 'For creators shipping shorts every week.',
    features: [
      '30 videos / month',
      '1080p exports, no watermark',
      'Unlimited clips per video',
      'Deeper AI analysis (larger model)',
      'All caption styles',
      'Speaker tracking reframe',
    ],
  },
  {
    tier: 'PRO',
    label: 'Pro',
    videosPerMonth: null,
    clipMinutesPerMonth: null,
    maxExportHeight: 2160,
    watermark: false,
    aiBroll: true,
    priorityProcessing: true,
    priceMonthlyUsd: 99,
    blurb: 'Teams and agencies producing at volume.',
    features: [
      'Unlimited videos',
      '4K exports',
      'Priority processing queue',
      'AI B-roll (LongCat GPU worker)',
      'Advanced export presets',
      'Team projects (coming soon)',
    ],
  },
];

export function planByTier(tier: PlanTier): PlanLimits {
  return PLANS.find((p) => p.tier === tier) ?? PLANS[0];
}
