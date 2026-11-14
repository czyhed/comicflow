import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { comicflowApi } from '../../api/client'
import { currentVisual, usesNativeAudio } from '../../production-readiness'
import { useWorkspace } from '../../stores/workspace'
import type { Shot, Snapshot, TimelineSegment } from '../../types'
import { EmptyWorkspace } from '../script/ScriptWorkspace'

export function AudioWorkspace({ snapshot }: { snapshot?: Snapshot }) {
  const { selectedShotId } = useWorkspace()
  const shots = snapshot?.script?.shots ?? []
  const shot = shots.find(item => item.id === selectedShotId) ?? shots[0]
  if (!snapshot || !shot) return <EmptyWorkspace title="先准备剧本，再检查声音与字幕" />
  return <ShotSound key={`${snapshot.project.id}:${shot.id}`} snapshot={snapshot} shot={shot} />
}

function ShotSound({ snapshot, shot }: { snapshot: Snapshot; shot: Shot }) {
  const { setActiveModule, setSelectedShotId } = useWorkspace()
  const queryClient = useQueryClient()
  const visual = currentVisual(snapshot, shot.id)
  const native = usesNativeAudio(visual)
  const audioAsset = [...snapshot.audioAssets].reverse().find(asset => asset.valid && asset.shotId === shot.id)
  const videoUrl = typeof visual?.downloadUrl === 'string' ? visual.downloadUrl : undefined
  const audioUrl = typeof audioAsset?.downloadUrl === 'string' ? audioAsset.downloadUrl : undefined
  const timeline = snapshot.timelines?.[shot.id]
  const durationMs = timeline?.durationMs ?? shot.durationSec * 1000
  const [playheadMs, setPlayheadMs] = useState(0)
  const [mediaError, setMediaError] = useState(false)
  const mediaRef = useRef<HTMLMediaElement | null>(null)
  const generate = useMutation({
    mutationFn: () => comicflowApi.generateAudio(snapshot.project.id, shot.id, snapshot.project.version),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['snapshot', snapshot.project.id] }),
  })
  const navigate = (module: 'script' | 'visuals' | 'export') => {
    setSelectedShotId(shot.id)
    setActiveModule(module)
  }
  const refreshMedia = () => void queryClient.invalidateQueries({ queryKey: ['snapshot', snapshot.project.id] })
  const mediaEvents = {
    onTimeUpdate: () => setPlayheadMs((mediaRef.current?.currentTime ?? 0) * 1000),
    onError: () => setMediaError(true),
    onLoadedData: () => setMediaError(false),
  }
  const tracks: Array<{ label: string; key: string; type: string; segments: TimelineSegment[] }> = timeline ? [
    { label: '动作', key: 'action', type: 'action', segments: timeline.actionTrack },
    { label: '表情', key: 'expression', type: 'expression', segments: timeline.expressionTrack },
    { label: '对白', key: 'dialogue', type: 'voice', segments: timeline.dialogue },
    { label: '字幕草稿', key: 'subtitle', type: 'subtitle', segments: timeline.subtitle },
    ...(!native ? [{ label: '口型', key: 'lipsync', type: 'lips', segments: timeline.lipSyncTrack }] : []),
  ] : []

  return (
    <div className="sound-workspace">
      <header className="sound-heading">
        <div><h2>声音与字幕</h2><p>先试听已生成的素材，再检查剧本文字。</p></div>
        <label>镜头选择<select value={shot.id} onChange={event => setSelectedShotId(event.target.value)}>
          {snapshot.script?.shots.map(item => <option key={item.id} value={item.id}>{item.order}. {item.title}</option>)}
        </select></label>
      </header>
      <div className="sound-columns">
        <section className="sound-media" aria-label="声音预览">
          <h3>{native ? '视频原声' : '独立配音'}</h3>
          {native ? <>
            <p>直接试听 MiniMax 视频中的对白、旁白和环境声。合成时保留当前视频音轨。</p>
            {videoUrl ? <video key={videoUrl} ref={element => { mediaRef.current = element }}
              aria-label="当前镜头原声视频" src={videoUrl} controls preload="metadata" playsInline {...mediaEvents} />
              : <p>当前视频暂时没有可播放地址。<button onClick={refreshMedia}>刷新素材地址</button></p>}
            <p className="sound-note">不需要再次配音或生成口型。若有台词却没有音轨，合成会停止并提示原因。</p>
          </> : <>
            {audioUrl ? <audio key={audioUrl} ref={element => { mediaRef.current = element }}
              aria-label="当前镜头配音" src={audioUrl} controls preload="metadata" {...mediaEvents} />
              : <p>当前镜头尚无可播放的独立配音。</p>}
            {!visual ? <button className="full-command" onClick={() => navigate('visuals')}>到画面生成当前镜头</button>
              : (shot.dialogue?.trim() || shot.narration?.trim()) ? <>
                <p>独立配音可能调用模型并消耗额度。</p>
                <button className="full-command" onClick={() => generate.mutate()} disabled={generate.isPending}>
                  {generate.isPending ? '配音处理中…' : audioAsset ? '重新生成对白与口型' : '生成当前镜头配音'}
                </button>
              </> : <p>当前剧本没有对白或旁白，无需生成独立配音。</p>}
          </>}
          {mediaError && <div role="alert" className="error-banner">媒体加载失败，请刷新地址后检查原文件。
            <button onClick={refreshMedia}>刷新素材地址</button>
          </div>}
          {generate.error && <p role="alert" className="error-banner">{generate.error instanceof Error ? generate.error.message : '配音失败，请核对已有调用记录。'}</p>}
          <div className={`preview-frame tone-${shot.order % 4}`} data-playhead-ms={playheadMs}>
            <small>当前动作：{activeSegment(timeline?.actionTrack ?? [], playheadMs)?.type ?? shot.action ?? '—'} · 当前表情：{activeSegment(timeline?.expressionTrack ?? [], playheadMs)?.type ?? shot.emotion ?? '—'}</small>
          </div>
        </section>
        <section className="sound-script dialogue-editor" aria-label="剧本文字与字幕说明">
          <h3>当前已保存剧本</h3>
          <p>以下文字来自剧本，不是对视频声音的识别结果。</p>
          <label>已保存对白<textarea readOnly value={shot.dialogue ?? ''} placeholder="无对白" /></label>
          <label>已保存旁白<textarea readOnly value={shot.narration ?? ''} placeholder="无旁白" /></label>
          <button onClick={() => navigate('script')}>到剧本编辑台词</button>
          <p className="sound-note">修改剧本不会改掉已有视频里的声音；新台词需要在重新生成的视频中验收。</p>
          <h3>字幕草稿</h3>
          <p>字幕尚未进行语音时间对齐</p>
          <p className="sound-note">导出字幕按剧本文字和镜头时长生成。请核对实际台词、停顿与说话人，当前不代表逐句同步。</p>
          <button className="full-command" onClick={() => navigate('export')}>到导出合成</button>
        </section>
      </div>
      {timeline && <section className="sound-timeline" aria-label="已有镜头时间轴">
        <div className="editor-toolbar"><strong>音画时间轴</strong><span>{formatTime(playheadMs)} / {formatTime(durationMs)}</span></div>
        <div className="timeline">
          <input className="timeline-scrubber" type="range" aria-label="镜头播放头" min={0} max={durationMs}
            step={1} value={Math.min(playheadMs, durationMs)} onChange={event => {
              const ms = Number(event.target.value)
              setPlayheadMs(ms)
              if (mediaRef.current && mediaRef.current.readyState > 0) mediaRef.current.currentTime = ms / 1000
            }} />
          <div className="ruler"><span>00:00</span><span>{formatTime(durationMs / 2)}</span><span>{formatTime(durationMs)}</span></div>
          {tracks.map(({ label, key, type, segments }) => <div className="track" data-track={key} key={key}>
            <strong>{label}</strong><div>{segments.map((segment, index) => <i className={type} key={index}
              style={{ marginLeft: `${segment.startMs / Math.max(1, durationMs) * 100}%`, width: `${(segment.endMs - segment.startMs) / Math.max(1, durationMs) * 100}%` }}>
              {segment.text ?? segment.type ?? (segment.assetId ? '已有口型片段' : '')}
            </i>)}<span className="track-playhead" style={{ left: `${playheadMs / Math.max(1, durationMs) * 100}%` }} /></div>
          </div>)}
        </div>
      </section>}
    </div>
  )
}

function activeSegment(segments: TimelineSegment[], positionMs: number) {
  return segments.find(segment => positionMs >= segment.startMs && positionMs < segment.endMs)
}

function formatTime(milliseconds: number) {
  const seconds = Math.max(0, milliseconds) / 1000
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${(seconds % 60).toFixed(1).padStart(4, '0')}`
}
