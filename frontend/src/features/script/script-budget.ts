import type { Shot } from '../../types'

// Spoken characters only: CJK, latin letters and digits. Punctuation and speaker
// labels such as「林夏：」still count for the name, which keeps the hint conservative.
const SPOKEN = /[\u3400-\u9fffA-Za-z0-9]/g

export const SPEECH_CHARS_PER_SEC = 4
// Seconds left for action and reaction before speech may start or after it ends.
export const SPEECH_REACTION_SEC = 1

export type SpeechStatus = 'ok' | 'near' | 'over' | 'silent'

export function spokenLength(text: string | undefined) {
  return (text ?? '').match(SPOKEN)?.length ?? 0
}

export function speechBudget(shot: Pick<Shot, 'dialogue' | 'narration' | 'durationSec'>) {
  const used = spokenLength(shot.dialogue) + spokenLength(shot.narration)
  const limit = Math.max(0, Math.floor((shot.durationSec - SPEECH_REACTION_SEC) * SPEECH_CHARS_PER_SEC))
  const status: SpeechStatus = used === 0 ? 'silent' : used > limit ? 'over' : used > limit * 0.8 ? 'near' : 'ok'
  return { used, limit, status }
}

// Short shots with chained camera moves ("推进到车门，随后稳定在车厢内") were a
// recurring cause of unfinished actions; this is a hint only, nothing is rewritten.
const CHAINED_MOVE = /随后|然后|接着|紧接|之后/

export function hasChainedCameraMove(shot: Pick<Shot, 'cameraMovement' | 'durationSec'>) {
  return shot.durationSec <= 5 && CHAINED_MOVE.test(shot.cameraMovement ?? '')
}

export const SHOT_SIZES = ['远景', '全景', '中景', '近景', '特写', '大特写'] as const
