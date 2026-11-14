import type { Shot, Snapshot } from './types'

/** Whether a shot has spoken lines and needs an audio source. */
export function shotSpeaks(shot: Shot): boolean {
  return Boolean((shot.dialogue ?? '').trim() || (shot.narration ?? '').trim())
}

function validShotIds(assets: Array<Record<string, unknown>>): Set<string> {
  const ids = new Set<string>()
  for (const asset of assets) {
    if (asset.valid) ids.add(String(asset.shotId))
  }
  return ids
}

export function currentVisual(snapshot: Snapshot | undefined, shotId: string) {
  return [...(snapshot?.visualAssets ?? [])].reverse().find(asset => asset.valid && asset.shotId === shotId)
}

/** The adopted video's first frame (or adopted image) for shot thumbnails. */
export function shotPosterUrl(snapshot: Snapshot | undefined, shotId: string): string | undefined {
  const visual = currentVisual(snapshot, shotId)
  if (typeof visual?.posterUrl === 'string') return visual.posterUrl
  return visual?.mediaType === 'image' && typeof visual.downloadUrl === 'string' ? visual.downloadUrl : undefined
}

export function usesNativeAudio(visual: Record<string, unknown> | undefined): boolean {
  return Boolean(visual?.valid && visual.provider === 'minimax' && visual.mediaType === 'video')
}

export interface ProductionReadiness {
  shots: Shot[]
  /** Shots still missing a visual — every shot needs one. */
  missingVisual: Shot[]
  /** Speaking shots without native video sound that still need independent voices. */
  missingAudio: Shot[]
  /** Original soundtracks are checked in FFmpeg, not synthesized as separate voices. */
  nativeAudioShots: Shot[]
  visualDone: number
  audioDone: number
  /** Shots requiring independent voice assets, excluding native video soundtracks. */
  audioNeeded: number
  /** True when composition can be submitted; FFmpeg still checks the actual files. */
  composable: boolean
}

/**
 * Mirror of the server's composition gate so the UI can explain, and prevent,
 * a refusal before spending a request: every shot needs a visual, and every
 * speaking shot needs an independent voice or native H3 footage. The latter's
 * audio stream is validated by the compositor, not inferred from this metadata.
 */
export function readProductionReadiness(snapshot: Snapshot | undefined): ProductionReadiness {
  const shots = snapshot?.script?.shots ?? []
  const withVisual = validShotIds(snapshot?.visualAssets ?? [])
  const withAudio = validShotIds(snapshot?.audioAssets ?? [])
  const missingVisual = shots.filter((shot) => !withVisual.has(shot.id))
  const nativeAudioShots = shots.filter(shot => usesNativeAudio(currentVisual(snapshot, shot.id)))
  const speaking = shots.filter(shot => shotSpeaks(shot) && !nativeAudioShots.includes(shot))
  const missingAudio = speaking.filter((shot) => !withAudio.has(shot.id))
  return {
    shots,
    missingVisual,
    missingAudio,
    nativeAudioShots,
    visualDone: shots.length - missingVisual.length,
    audioDone: speaking.length - missingAudio.length,
    audioNeeded: speaking.length,
    composable: shots.length > 0 && missingVisual.length === 0 && missingAudio.length === 0,
  }
}

/** Short Chinese summary of what is still missing, for buttons and hints. */
export function describeMissing(readiness: ProductionReadiness): string {
  const parts: string[] = []
  if (readiness.missingVisual.length) parts.push(`${readiness.missingVisual.length} 个镜头缺画面`)
  if (readiness.missingAudio.length) parts.push(`${readiness.missingAudio.length} 个镜头缺配音`)
  return parts.join('、')
}
