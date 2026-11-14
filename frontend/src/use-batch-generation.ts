import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { comicflowApi } from './api/client'
import { readProductionReadiness, shotSpeaks, usesNativeAudio } from './production-readiness'
import type { Snapshot } from './types'
import { videoJobActive, videoJobError } from './video-jobs'

function pause(signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    signal.throwIfAborted()
    const abort = () => { clearTimeout(timer); reject(new Error('已停止后续镜头；已提交任务仍可在画面页查看')) }
    const timer = setTimeout(() => { signal.removeEventListener('abort', abort); resolve() }, 1500)
    signal.addEventListener('abort', abort, { once: true })
  })
}

export interface BatchProgress {
  /** Shots finished in the current run. */
  done: number
  /** Shots this run set out to generate. */
  total: number
  /** Shot title being generated right now, for the progress label. */
  current: string
  /** First failure, so a partial run reports why it stopped. */
  error?: string
  waitingShotId?: string
}

/**
 * Generate the missing assets for every shot, one shot at a time.
 *
 * Generation is sequential because each call advances the project version and
 * the next request must send the version the server just produced. Progress is
 * surfaced per shot so a long run stays legible instead of looking hung.
 */
export function useBatchGeneration(snapshot: Snapshot | undefined) {
  const queryClient = useQueryClient()
  const [progress, setProgress] = useState<BatchProgress | null>(null)
  const controller = useRef<AbortController | null>(null)
  useEffect(() => () => { controller.current?.abort() }, [snapshot?.project.id])

  const run = useMutation({
    mutationFn: async (target: 'visual' | 'audio' | 'both') => {
      if (!snapshot) throw new Error('SNAPSHOT_REQUIRED')
      controller.current?.abort()
      const signal = (controller.current = new AbortController()).signal
      const projectId = snapshot.project.id
      const readiness = readProductionReadiness(snapshot)
      const queue = readiness.shots.filter((shot) => {
        const needsVisual = readiness.missingVisual.includes(shot)
        const needsAudio = readiness.missingAudio.includes(shot)
        if (target === 'visual') return needsVisual
        if (target === 'audio') return needsAudio
        return needsVisual || needsAudio
      })
      let version = snapshot.project.version
      setProgress({ done: 0, total: queue.length, current: '' })
      for (const [index, shot] of queue.entries()) {
        setProgress({ done: index, total: queue.length, current: shot.title })
        try {
          signal.throwIfAborted()
          let generatedNativeVideo = false
          const saved = target === 'audio' ? [] : await comicflowApi.videoJobs(projectId)
          const waiting = readiness.shots.find(item => {
            const latest = saved.find(job => job.shotId === item.id)
            return latest?.status === 'succeeded' && !latest.result?.adopted
          })
          if (waiting) {
            setProgress({ done: index, total: queue.length, current: waiting.title, waitingShotId: waiting.id })
            return index
          }
          if (target !== 'audio' && readiness.missingVisual.includes(shot)) {
            if (saved.some(job => job.shotId === shot.id && videoJobActive(job))) {
              throw new Error('该镜头已有未结束任务，请在画面页核查或恢复，未重复提交')
            }
            let job = await comicflowApi.queueVideo(projectId, shot.id, version, undefined, signal)
            void queryClient.invalidateQueries({ queryKey: ['video-jobs', projectId] })
            while (!['succeeded', 'failed', 'cancelled', 'recoverable', 'unknown'].includes(job.status)) {
              await pause(signal)
              job = await comicflowApi.videoJob(projectId, job.id, signal)
            }
            if (job.status !== 'succeeded') throw new Error(videoJobError(job) || '任务已中断，请在画面页核查')
            if (!job.result?.adopted) {
              setProgress({ done: index, total: queue.length, current: shot.title, waitingShotId: shot.id })
              return index
            }
            const fresh = await comicflowApi.snapshot(projectId)
            version = fresh.project.version
            generatedNativeVideo = usesNativeAudio(fresh.visualAssets.find(asset => asset.id === job.result?.assetId))
          }
          signal.throwIfAborted()
          // A voice needs its visual first, so audio follows in the same pass.
          if (target !== 'visual' && !generatedNativeVideo && shotSpeaks(shot) && readiness.missingAudio.includes(shot)) {
            const audio = await comicflowApi.generateAudio(projectId, shot.id, version)
            version = Number(audio.projectVersion ?? version)
          }
        } catch (error) {
          setProgress({
            done: index,
            total: queue.length,
            current: shot.title,
            error: error instanceof Error ? error.message : 'GENERATION_FAILED',
          })
          throw error
        }
        // Keep the workspace live so per-shot results appear as they land.
        void queryClient.invalidateQueries({ queryKey: ['snapshot', projectId] })
      }
      setProgress({ done: queue.length, total: queue.length, current: '' })
      return queue.length
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ['snapshot', snapshot?.project.id] })
      void queryClient.invalidateQueries({ queryKey: ['generation-session'] })
    },
  })

  return { run, progress, stop: () => controller.current?.abort(), reset: () => setProgress(null) }
}
