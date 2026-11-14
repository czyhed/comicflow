import { useState } from 'react'
import { shotPosterUrl } from '../production-readiness'
import type { Snapshot } from '../types'

// Decorative (alt=""): the shot title next to the thumbnail already names it.
// A missing or expired poster falls back to the coloured tone block underneath.
export function ShotPoster({ snapshot, shotId }: { snapshot?: Snapshot; shotId: string }) {
  const url = shotPosterUrl(snapshot, shotId)
  const [failed, setFailed] = useState<string>()
  if (!url || failed === url) return null
  return <img className="shot-poster" src={url} alt="" loading="lazy" onError={() => setFailed(url)} />
}
