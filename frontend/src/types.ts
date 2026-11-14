export type WorkflowMode = 'guided' | 'automatic' | 'import_story' | 'import_script'

export interface VisualPreflight {
  ready: boolean
  fingerprint: string | null
  model: string | null
  adapter?: string
  modelConfigRevision?: number
  textModel?: string | null
  parameters: Record<string, string | number | boolean>
  mode?: string
  references: { label: string; role: string; name?: string; view?: string; sourceId: string; fileState: string }[]
  prompt: { kind: 'submission' | 'expansion-input'; text: string; system?: string; platformOptimization: boolean; rules?: Record<string, unknown> } | null
  calls: { text: number; video: number } | null
  price: null
  errors: string[]
  warnings: string[]
  style?: { name: string; revision: number } | null
  speech?: { dialogue: string; narration: string }
  camera?: { visualDescription: string; cameraMovement: string }
  speechReview?: {
    spokenCharacterCount: number
    narrationCharacterCount: number
    totalCharacterCount: number
    estimatedSpeechSec: number
    durationSec: number
    severity: string
  }
  actionStates?: { actionBefore: string; actionMiddle: string; actionAfter: string }
}

export interface Shot {
  id: string
  order: number
  title: string
  action: string
  emotion: string
  shotSize: string
  durationSec: number
  visualDescription: string
  dialogue: string
  narration: string
  characterIds?: string[]
  characters?: string[]
  cameraMovement?: string
  visualStyle?: string
  soundscape?: string
  music?: string
  generationMode?: string
  sceneId?: string
  actionBefore?: string
  actionMiddle?: string
  actionAfter?: string
}

export interface Script {
  title: string
  scenes: Array<{ id: string; title: string; shotIds: string[]; time?: string; location?: string; narrativeGoal?: string; conflict?: string; turningPoint?: string; lighting?: string; weather?: string }>
  shots: Shot[]
}

export interface CharacterCard {
  id: string
  projectId?: string
  name: string
  appearance: string
  clothing: string
  personality: string
  voice: { provider?: string; voiceId?: string; language?: string }
  referenceImageUrl?: string
  referenceImageMediaType?: string
  referenceImagePrompt?: string
  referenceImageStatus?: 'none' | 'candidate' | 'approved' | 'views-partial' | 'views-ready'
  referenceImageCandidate?: CharacterReferenceAsset | null
  referenceViews?: CharacterReferenceAsset[]
  referenceBoard?: { id?: string; objectKey?: string; url?: string; status?: 'approved' | 'stale' }
  referenceBoardCandidate?: CharacterReferenceAsset | null
  revision?: number
}

export interface CharacterReferenceAsset {
  generationMode?: string
  id: string
  url: string
  objectKey?: string | null
  mediaType: 'image'
  status?: 'candidate' | 'approved' | 'stale'
  view?: 'front' | 'three-quarter' | 'profile'
  viewLabel?: string
  characterRevision?: number
  sourceReferenceId?: string
}

export type CharacterPromptFields = Pick<CharacterCard, 'name' | 'appearance' | 'clothing' | 'personality'> & { referenceImagePrompt: string }
export type CharacterSettingField = 'appearance' | 'clothing' | 'personality'
export type CharacterPromptPurpose = 'settings' | 'reference-image'

export interface CharacterPromptPreview {
  draft: Pick<CharacterPromptFields, 'name'> & Partial<Omit<CharacterPromptFields, 'name'>>
  expectedVersion: number
  expectedRevision: number | null
}

export interface ScriptPreview {
  expectedVersion: number
  script: Script
  summary: { scenes: number; shots: number; dialogue: number; narration: number; issues: string[] }
}

export interface VisualStyleProfile {
  presetId: string
  revision: number
  name: string
  medium: string
  description: string
  rendering: string
  lighting: string
  motion: string
  avoid: string
}

export interface Project {
  id: string
  stage: string
  version: number
  input: { inputType: 'idea' | 'story'; story: string; durationSec: number; mode: WorkflowMode }
  estimate: { shots: number; creditMin: number; creditMax: number }
  script?: Script
  generatedStoryText?: string | null
  storyTextVersion?: number
  generationSession?: GenerationSession
  exportManifest?: { files: string[] } | null
  referenceImage?: ReferenceImageAsset | null
  referenceImages?: ReferenceImageAsset[]
  visualStyleProfile?: VisualStyleProfile | null
}

export interface ReferenceImageAsset {
  id: string
  type: string
  mediaType: string
  sizeBytes: number
  sha256: string
  objectKey: string
  filename: string
  valid: boolean
  downloadUrl?: string
}

export interface GuidedSession {
  questionCount: number
  maxQuestions: number
  currentQuestion: string
  transcript: Array<{ question: string; answer: string; questionId?: string; questionType?: string; missingFields?: string[] }>
  done: boolean
  detailGenerated?: boolean
  currentQuestionId?: string
  currentQuestionType?: string
  currentMissingFields?: string[]
}

export interface GenerationSession {
  id: string
  projectId: string
  mode: WorkflowMode
  stage: string
  status: string
  retryCount: number
  lastError?: string | null
  pauseReason?: string
  waitingJobId?: string
  waitingShotId?: string
  guided?: GuidedSession
}

export interface Snapshot {
  project: Project
  script?: Script
  jobs: Array<{ id: string; type: string; status: string; progress?: number; error?: string; shotIds?: string[]; exportManifest?: { files: string[] } }>
  creditLedger: Array<{ type: string; amount: number; consumed?: number }>
  visualAssets: Array<Record<string, unknown>>
  audioAssets: Array<Record<string, unknown>>
  lipSyncAssets: Array<Record<string, unknown>>
  timelines: Record<string, ShotTimeline>
  exportManifest?: { files: string[] } | null
}

export interface TimelineSegment {
  type?: string
  text?: string
  assetId?: string
  startMs: number
  endMs: number
}

export interface VideoJob {
  id: string
  projectId: string
  shotId: string
  status: string
  taskId?: string | null
  createdAt: string
  updatedAt: string
  model?: string
  modelConfigRevision?: number
  parameters: Record<string, unknown>
  error?: string | null
  errorDetail?: Record<string, unknown>
  callsStarted: { text: number; video: number }
  attempts: number
  history: Array<{ status: string; at: string }>
  canRecover: boolean
  canLinkTask: boolean
  result?: { assetId: string; adopted: boolean; projectVersion: number } | null
}

export interface ShotTimeline {
  shotId: string
  durationMs: number
  visualAssetId: string
  actionTrack: TimelineSegment[]
  expressionTrack: TimelineSegment[]
  cameraTrack: TimelineSegment[]
  dialogue: TimelineSegment[]
  subtitle: TimelineSegment[]
  lipSyncTrack: TimelineSegment[]
}
export type ImageJob = {
  id: string
  projectId: string
  characterId: string
  purpose: 'candidate' | 'views' | 'board' | 'text-board'
  status: string
  currentStep?: string | null
  taskId?: string | null
  error?: string | null
  errorDetail?: { stage?: string; transportError?: string; upstreamStatus?: number; upstreamCode?: string; requestId?: string } | null
  createdAt: string
  updatedAt: string
  callsStarted: number
  completedSteps: string[]
  canRecover: boolean
  applied?: boolean
  assets?: { id: string; step: string; url: string | null }[]
}
