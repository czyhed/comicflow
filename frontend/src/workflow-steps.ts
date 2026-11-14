import { readProductionReadiness } from './production-readiness'
import type { Snapshot } from './types'

export type StepModule = 'create' | 'script' | 'storyboard' | 'characters' | 'visuals' | 'audio' | 'export'
export interface StepStatus { done: boolean; hint?: string }

const BEFORE_CONFIRM = new Set(['created', 'story', 'story-generating', 'story-generated',
  'script-generating', 'script-completed', 'awaiting-confirmation'])

/**
 * Display-only progress for the module navigation. It reads the snapshot already
 * loaded by the app and never gates navigation; the server stays authoritative.
 */
export function workflowSteps(snapshot: Snapshot | undefined): Partial<Record<StepModule, StepStatus>> {
  if (!snapshot?.project) return {}
  const stage = snapshot.project.stage ?? ''
  const script = snapshot.script
  const confirmed = Boolean(script) && !BEFORE_CONFIRM.has(stage)
  const readiness = readProductionReadiness(snapshot)
  const shots = readiness.shots.length
  const steps: Partial<Record<StepModule, StepStatus>> = {
    create: { done: Boolean(snapshot.project.generatedStoryText || script) },
    script: { done: confirmed, hint: script && !confirmed ? '待确认' : undefined },
    storyboard: { done: confirmed },
  }
  if (confirmed && shots > 0) {
    steps.visuals = { done: readiness.missingVisual.length === 0, hint: `${readiness.visualDone}/${shots}` }
    steps.audio = readiness.audioNeeded > 0
      ? { done: readiness.missingAudio.length === 0, hint: `${readiness.audioDone}/${readiness.audioNeeded}` }
      : { done: readiness.missingVisual.length === 0 }
  }
  steps.export = { done: Boolean(snapshot.exportManifest) }
  return steps
}
