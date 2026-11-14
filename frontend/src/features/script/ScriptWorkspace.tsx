import { TextGenerationProgress, useTextGenerationProgress } from './TextGenerationProgress'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Check, CircleAlert, Clapperboard, ImagePlus, Mic, Sparkles } from 'lucide-react'
import { Fragment, useEffect, useRef, useState } from 'react'
import { comicflowApi } from '../../api/client'
import { useWorkspace } from '../../stores/workspace'
import type { Script, ScriptPreview, Shot, Snapshot } from '../../types'
import { ScriptPreviewPanel } from './ScriptPreviewPanel'
import { SHOT_SIZES, hasChainedCameraMove, speechBudget, type SpeechStatus } from './script-budget'

const pad = (value: number) => String(value).padStart(2, '0')
const sceneFieldLabels = { time: '时间', location: '地点', lighting: '光线', weather: '天气', narrativeGoal: '叙事目标', conflict: '冲突', turningPoint: '转折' } as const
const styleFieldLabels = { visualStyle: '视觉风格', soundscape: '环境声', music: '配乐' } as const

function speechBadge(status: SpeechStatus, used: number, limit: number) {
  if (status === 'silent') return '无台词'
  if (status === 'over') return `台词超出 ${used}/${limit}`
  if (status === 'near') return `接近上限 ${used}/${limit}`
  return `台词 ${used}/${limit}`
}

function shotsOfScene(script: Script, sceneId: string | undefined) {
  // Legacy scripts without scenes still need every shot to stay editable.
  if (script.scenes.length === 0) return script.shots
  const scene = script.scenes.find((item) => item.id === sceneId)
  const ids = new Set(scene?.shotIds ?? [])
  return script.shots.filter((shot) => ids.has(shot.id) || (sceneId !== undefined && shot.sceneId === sceneId))
}

function cloneScript(script: Script): Script {
  return JSON.parse(JSON.stringify(script)) as Script
}

function sceneForShot(script: Script | undefined, shotId: string | null) {
  const shot = script?.shots.find(item => item.id === shotId)
  return script?.scenes.find(scene => scene.shotIds.includes(shotId ?? '') || scene.id === shot?.sceneId)?.id
    ?? script?.scenes[0]?.id
}

function scriptIssues(script: Script): string[] {
  const issues: string[] = []
  if (script.shots.length < 6) issues.push('镜头数量不足')
  if (script.scenes.some((scene) => !scene.time || !scene.location || !scene.narrativeGoal || !scene.conflict || !scene.turningPoint)) issues.push('场景信息不完整')
  if (script.shots.some((shot) => typeof shot.dialogue !== 'string' || typeof shot.narration !== 'string')) issues.push('存在台词字段不完整的镜头')
  const shotIds = new Set(script.shots.map((shot) => shot.id))
  if (script.scenes.some((scene) => scene.shotIds.some((shotId) => !shotIds.has(shotId)))) issues.push('场景与镜头引用不一致')
  return issues
}

export function ScriptWorkspace({ snapshot }: { snapshot?: Snapshot }) {
  const { projectId, setActiveModule, selectedShotId, setSelectedShotId } = useWorkspace()
  const [draftScript, setDraftScript] = useState<Script | undefined>(snapshot?.script)
  const [draftVersion, setDraftVersion] = useState(snapshot?.project.version ?? 1)
  const [dirty, setDirty] = useState(false)
  const [preview, setPreview] = useState<ScriptPreview>()
  const [saveMessage, setSaveMessage] = useState('已自动保存')
  const [selectedSceneId, setSelectedSceneId] = useState<string | undefined>(() => sceneForShot(snapshot?.script, selectedShotId))
  const queryClient = useQueryClient()
  const progress = useTextGenerationProgress()
  const split = useMutation({
    onMutate: progress.reset,
    mutationFn: () => {
      if (!projectId) throw new Error('PROJECT_REQUIRED')
      return comicflowApi.previewScript(projectId, progress.receive)
    },
    onSuccess: (result) => { setPreview(result); commitPreview.reset() },
  })
  const commitPreview = useMutation({
    mutationFn: () => {
      if (!projectId || !preview) throw new Error('PROJECT_REQUIRED')
      return comicflowApi.commitScriptPreview(projectId, preview)
    },
    onSuccess: (result) => {
      setPreview(undefined)
      setDraftScript(cloneScript(result.script))
      setSelectedSceneId(result.script.scenes[0]?.id)
      setDraftVersion(result.project.version)
      setDirty(false)
      setSaveMessage('剧本已拆分，可继续编辑')
      queryClient.setQueryData(['snapshot', projectId], (current: Snapshot | undefined) => current ? { ...current, project: result.project, script: result.script } : current)
      void queryClient.invalidateQueries({ queryKey: ['snapshot', projectId] })
    },
  })
  useEffect(() => {
    if (!dirty && snapshot?.script && snapshot.project.version >= draftVersion) {
      setDraftScript(cloneScript(snapshot.script))
      setSelectedSceneId((current) => current && snapshot.script?.scenes.some((scene) => scene.id === current) ? current : sceneForShot(snapshot.script, selectedShotId))
    }
    if (!dirty && snapshot?.project.version && snapshot.project.version >= draftVersion) setDraftVersion(snapshot.project.version)
  }, [snapshot?.project.id, snapshot?.project.version, snapshot?.script, dirty, draftVersion, selectedShotId])
  const previousPreview = useRef(preview)
  const background = useMutation({
    mutationFn: () => {
      if (!projectId || !selectedScene || dirty) throw new Error('请先保存剧本修改')
      return comicflowApi.generateProjectReference(projectId, 'scenes', selectedScene.id, draftVersion)
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['snapshot', projectId] }),
  })
  useEffect(() => {
    // After committing a preview the editor replaces it; bring its top into view.
    if (previousPreview.current && !preview) {
      document.querySelector('.three-column')?.scrollIntoView({ block: 'start', behavior: 'smooth' })
    }
    previousPreview.current = preview
  }, [preview])
  const script = draftScript ?? snapshot?.script
  const selectedScene = script?.scenes.find((scene) => scene.id === selectedSceneId) ?? script?.scenes[0]
  const visibleShots = script ? shotsOfScene(script, selectedScene?.id) : []
  const hasScript = Boolean(script)
  useEffect(() => {
    // Arriving from the storyboard with a shot selected: bring that shot card into view.
    if (hasScript && selectedShotId) document.getElementById(`script-shot-${selectedShotId}`)?.scrollIntoView({ block: 'start' })
    // Only on first render of a loaded script; later jumps scroll explicitly.
  }, [hasScript])
  const issues = script ? scriptIssues(script) : []
  const updateScriptDraft = (patch: Partial<Script>) => {
    setDraftScript((current) => current ? { ...current, ...patch } : current)
    setDirty(true)
    setSaveMessage('有未保存修改')
  }
  const updateShot = (shotId: string, patch: Partial<Shot>) => {
    if (!script) return
    updateScriptDraft({ shots: script.shots.map((shot) => shot.id === shotId ? { ...shot, ...patch } : shot) })
  }
  const save = useMutation({
    mutationFn: () => {
      if (!projectId || !script || !snapshot) throw new Error('PROJECT_REQUIRED')
      return comicflowApi.updateScript(projectId, script, draftVersion)
    },
    onSuccess: (result) => {
      setDraftScript(cloneScript(result.script))
      setDraftVersion(result.project.version)
      setDirty(false)
      setSaveMessage('已保存')
      void queryClient.invalidateQueries({ queryKey: ['snapshot', projectId] })
    },
    onError: (error) => setSaveMessage(error instanceof Error ? error.message : '保存失败'),
  })
  const confirm = useMutation({
    mutationFn: async () => {
      if (!projectId || !script || !snapshot) throw new Error('PROJECT_REQUIRED')
      const saved = dirty ? await comicflowApi.updateScript(projectId, script, draftVersion) : { project: { ...snapshot.project, version: draftVersion } }
      return comicflowApi.confirmScript(projectId, saved.project.version)
    },
    onSuccess: async (result) => {
      setDirty(false)
      setSaveMessage('已保存')
      // Confirmation advances the persisted production session as well as the project.
      // Seed the session cache from that response so AppShell cannot render the
      // pre-confirmation checkpoint while the snapshot query is being refreshed.
      if (projectId && result.project.generationSession) {
        queryClient.setQueryData(['generation-session', projectId], result.project.generationSession)
      }
      await queryClient.invalidateQueries({ queryKey: ['snapshot', projectId] })
      setActiveModule('storyboard')
    },
  })
  if (preview) return <ScriptPreviewPanel preview={preview} pending={commitPreview.isPending} error={commitPreview.error}
    onCancel={() => { setPreview(undefined); commitPreview.reset() }} onConfirm={() => commitPreview.mutate()} />
  if (!script && snapshot?.project.generatedStoryText) {
    return <section className="script-split-panel">
      <div className="editor-toolbar"><div><strong>剧本拆分</strong><span>创建页已生成故事文本</span></div><button className="editor-save" onClick={() => split.mutate()} disabled={split.isPending}>{split.isPending ? '正在拆分…' : '拆分为剧本'}</button></div>
      {split.isPending && <TextGenerationProgress {...progress} kind="script" />}
      <article className="story-source-paper"><span className="eyebrow">故事原文</span><h2>待拆分的故事文本</h2><p>{snapshot.project.generatedStoryText}</p></article>
      {split.error && <div className="error-banner" role="alert">{(split.error as Error).message}<button onClick={() => split.mutate()}>重试拆分</button></div>}
    </section>
  }
  if (!script) return <EmptyWorkspace title="尚未生成剧本" />
  const totalSec = script.shots.reduce((sum, shot) => sum + shot.durationSec, 0)
  const targetSec = snapshot?.project.input?.durationSec
  const overBudget = script.shots.filter((shot) => speechBudget(shot).status === 'over').length
  const sceneIndex = Math.max(0, script.scenes.findIndex((scene) => scene.id === selectedScene?.id))
  const updateScene = (patch: Partial<Script['scenes'][number]>) => {
    if (!selectedScene) return
    updateScriptDraft({ scenes: script.scenes.map((scene) => scene.id === selectedScene.id ? { ...scene, ...patch } : scene) })
  }
  const selectScene = (sceneId: string) => {
    setSelectedSceneId(sceneId)
    document.querySelector('.script-editor .editor-panel')?.scrollTo({ top: 0 })
  }
  const jumpToShot = (shotId: string) => {
    setSelectedShotId(shotId)
    document.getElementById(`script-shot-${shotId}`)?.scrollIntoView({ block: 'start', behavior: 'smooth' })
  }
  return (
    <div className="three-column script-editor">
      <aside className="asset-list">
        <div className="column-title"><strong>场景</strong><span>{script.scenes.length}</span></div>
        {script.scenes.map((scene, index) => {
          const active = scene.id === selectedScene?.id
          const sceneShots = shotsOfScene(script, scene.id)
          return <Fragment key={scene.id}>
            <button className={active ? 'selected' : ''} onClick={() => selectScene(scene.id)}>
              <i>{pad(index + 1)}</i>
              <span><strong>{scene.title}</strong><small>{sceneShots.length} 个镜头 · {sceneShots.reduce((sum, shot) => sum + shot.durationSec, 0)} 秒</small></span>
            </button>
            {active && sceneShots.length > 0 && <ol className="scene-shot-outline">
              {sceneShots.map((shot, shotIndex) => {
                const budget = speechBudget(shot)
                return <li key={shot.id}><button type="button" aria-label={`跳到镜头 ${shot.order ?? shotIndex + 1}`} className={shot.id === selectedShotId ? 'current' : ''} onClick={() => jumpToShot(shot.id)}>
                  <b>{pad(shot.order ?? shotIndex + 1)}</b><span>{shot.title || '未命名镜头'}</span><em className={`speech-dot ${budget.status}`} />{shot.durationSec}s
                </button></li>
              })}
            </ol>}
          </Fragment>
        })}
      </aside>
      <section className="editor-panel">
        <div className="editor-toolbar"><div><strong>剧本编辑器</strong><span><Check size={13} /> {saveMessage}</span></div><button className="editor-save" onClick={() => save.mutate()} disabled={!dirty || save.isPending}>{save.isPending ? '保存中…' : '保存剧本'}</button></div>
        {issues.length > 0 && <div className="error-banner script-integrity-warning"><strong>剧本需要重新拆分</strong>{issues.map((issue) => <span key={issue}>{issue}</span>)}{snapshot?.project.generatedStoryText && <button onClick={() => split.mutate()} disabled={split.isPending}>{split.isPending ? '正在重新拆分…' : '重新拆分剧本'}</button>}</div>}
        {split.error && <div className="error-banner" role="alert">重新拆分失败，旧剧本未被覆盖：{split.error.message}</div>}
        {split.isPending && <TextGenerationProgress {...progress} kind="script" />}
        <article className="script-paper">
          <header className="script-head">
            <label className="script-title-field">剧本标题<input aria-label="剧本标题" value={script.title} onChange={(event) => updateScriptDraft({ title: event.target.value })} /></label>
            <div className="script-stats" aria-label="剧本概况">
              <span><strong>{script.scenes.length}</strong>场景</span>
              <span><strong>{script.shots.length}</strong>镜头</span>
              <span className={targetSec && totalSec !== targetSec ? 'warn' : ''}><strong>{totalSec}{targetSec ? `/${targetSec}` : ''}</strong>秒</span>
              <span className={overBudget ? 'danger' : ''}><strong>{overBudget}</strong>台词超长</span>
            </div>
          </header>
          {selectedScene && <section className="scene-card" aria-label="场景信息">
            <div className="scene-card-head">
              <span className="scene-index">场景 {pad(sceneIndex + 1)}</span>
              <label className="scene-title-field">场景标题<input aria-label="场景标题" value={selectedScene.title} onChange={(event) => updateScene({ title: event.target.value })} /></label>
              <button className="ghost-button" title={dirty ? '请先保存剧本修改' : undefined} disabled={dirty || background.isPending} onClick={() => background.mutate()}><ImagePlus size={14} />{background.isPending ? '正在生成场景参考图…' : '准备场景参考图（图片 API，可能计费）'}</button>
            </div>
            {background.isSuccess && <p className="inline-status" role="status">场景参考图已准备，已有图片会复用。</p>}
            {background.error && <p className="inline-status danger" role="alert">{background.error.message}</p>}
            <div className="scene-meta-grid">
              {(['time', 'location', 'lighting', 'weather'] as const).map((field) => <label key={field}>{sceneFieldLabels[field]}<input aria-label={`场景-${field}`} placeholder={field === 'lighting' ? '主光方向与色温，同场镜头沿用' : field === 'weather' ? '如：暴雨、晴、室内' : undefined} value={selectedScene[field] ?? ''} onChange={(event) => updateScene({ [field]: event.target.value })} /></label>)}
            </div>
            <div className="scene-story-grid">
              {(['narrativeGoal', 'conflict', 'turningPoint'] as const).map((field) => <label key={field}>{sceneFieldLabels[field]}<textarea rows={2} aria-label={`场景-${field}`} value={selectedScene[field] ?? ''} onChange={(event) => updateScene({ [field]: event.target.value })} /></label>)}
            </div>
          </section>}
          {visibleShots.map((shot, index) => {
            const budget = speechBudget(shot)
            const sameSizeAsPrevious = index > 0 && Boolean(shot.shotSize) && visibleShots[index - 1].shotSize === shot.shotSize
            return <section id={`script-shot-${shot.id}`} className={`shot-card${shot.id === selectedShotId ? ' current' : ''}`} key={shot.id} aria-label={`镜头 ${shot.order ?? index + 1}`}>
              <header className="shot-card-head">
                <span className="shot-index">{pad(shot.order ?? index + 1)}</span>
                <label className="shot-title-field">镜头标题<input aria-label={`镜头标题-${shot.id}`} value={shot.title} onChange={(event) => updateShot(shot.id, { title: event.target.value })} /></label>
                <label className="shot-size-field">景别<input aria-label={`景别-${shot.id}`} list="script-shot-sizes" value={shot.shotSize} onChange={(event) => updateShot(shot.id, { shotSize: event.target.value })} /></label>
                <label className="shot-duration-field">时长（秒）<input aria-label={`时长-${shot.id}`} type="number" min="1" value={shot.durationSec} onChange={(event) => updateShot(shot.id, { durationSec: Number(event.target.value) || 1 })} /></label>
                <span className={`speech-badge ${budget.status}`} title="按每秒约 4 字、预留 1 秒动作反应估算">{speechBadge(budget.status, budget.used, budget.limit)}</span>
              </header>
              {sameSizeAsPrevious && <p className="shot-hint"><CircleAlert size={13} />与上一镜头景别相同，可考虑切换景别让节奏更有变化。</p>}
              <div className="shot-card-body">
                <div className="shot-column">
                  <h4><Clapperboard size={14} />画面</h4>
                  <label>画面描述<textarea rows={3} aria-label={`画面描述-${shot.id}`} value={shot.visualDescription} onChange={(event) => updateShot(shot.id, { visualDescription: event.target.value })} /></label>
                  {shot.visualDescription.trim() && !/[\u3400-\u9fff]/.test(shot.visualDescription) && <p className="inline-status" role="status">此镜头保留了旧版英文描述，可直接改为中文并保存，无需重新生成。</p>}
                  <div className="shot-pair">
                    <label>动作<input aria-label={`动作-${shot.id}`} value={shot.action} onChange={(event) => updateShot(shot.id, { action: event.target.value })} /></label>
                    <label>情绪<input aria-label={`情绪-${shot.id}`} value={shot.emotion} onChange={(event) => updateShot(shot.id, { emotion: event.target.value })} /></label>
                  </div>
                  <label>运镜<textarea rows={2} aria-label={`cameraMovement-${shot.id}`} value={shot.cameraMovement ?? ''} onChange={(event) => updateShot(shot.id, { cameraMovement: event.target.value })} /></label>
                  {hasChainedCameraMove(shot) && <p className="shot-hint"><CircleAlert size={13} />{shot.durationSec} 秒镜头写了多段运镜，建议只保留一种，否则动作容易做不完。</p>}
                </div>
                <div className="shot-column">
                  <h4><Mic size={14} />声音</h4>
                  <label>对白<textarea rows={3} aria-label={`对白-${shot.id}`} placeholder="无对白可留空" value={shot.dialogue} onChange={(event) => updateShot(shot.id, { dialogue: event.target.value })} /></label>
                  <label>旁白<textarea rows={2} aria-label={`旁白-${shot.id}`} placeholder="无旁白可留空" value={shot.narration} onChange={(event) => updateShot(shot.id, { narration: event.target.value })} /></label>
                  <p className={`speech-meter ${budget.status}`}><span style={{ width: `${budget.limit ? Math.min(100, (budget.used / budget.limit) * 100) : budget.used ? 100 : 0}%` }} />本镜建议对白加旁白不超过 {budget.limit} 字，当前 {budget.used} 字</p>
                </div>
              </div>
              <details className="action-phases">
                <summary>动作三阶段（可选，用于精确控制动作完整性）</summary>
                <label>动作开始前<textarea aria-label={`动作开始前-${shot.id}`} placeholder="描述动作开始前的状态，如：手放在门把手上，站在门外" value={shot.actionBefore ?? ''} onChange={(event) => updateShot(shot.id, { actionBefore: event.target.value })} /></label>
                <label>动作进行中<textarea aria-label={`动作进行中-${shot.id}`} placeholder="描述动作的核心过程，如：推开门，身体从门外移动到门内" value={shot.actionMiddle ?? ''} onChange={(event) => updateShot(shot.id, { actionMiddle: event.target.value })} /></label>
                <label>动作结束后<textarea aria-label={`动作结束后-${shot.id}`} placeholder="描述动作完成后的状态，如：整个身体和双脚都进入房间，门在身后" value={shot.actionAfter ?? ''} onChange={(event) => updateShot(shot.id, { actionAfter: event.target.value })} /></label>
              </details>
              <details className="action-phases">
                <summary>风格与声音设计（视觉风格、环境声、配乐）</summary>
                <div className="shot-style-grid">{(['visualStyle', 'soundscape', 'music'] as const).map((field) => <label key={field}>{styleFieldLabels[field]}<textarea rows={2} aria-label={`${field}-${shot.id}`} value={shot[field] ?? ''} onChange={(event) => updateShot(shot.id, { [field]: event.target.value })} /></label>)}</div>
              </details>
            </section>
          })}
          <datalist id="script-shot-sizes">{SHOT_SIZES.map((size) => <option key={size} value={size} />)}</datalist>
        </article>
        {confirm.error && <div className="error-banner" role="alert">{(confirm.error as Error).message}</div>}
        {save.error && <div className="error-banner" role="alert">{(save.error as Error).message}</div>}
        <div className="editor-footer">
          <span>{script.shots.length} 个镜头 · {totalSec} 秒{dirty && <em className="unsaved-hint"> · 有未保存修改</em>}</span>
          <button onClick={() => confirm.mutate()} disabled={confirm.isPending}>{confirm.isPending ? '正在保存…' : '确认剧本并生成分镜'}</button>
        </div>
      </section>
    </div>
  )
}

export function EmptyWorkspace({ title }: { title: string }) { return <div className="empty-workspace"><Sparkles size={22} /><strong>{title}</strong><span>请先在创建模块完成故事生成。</span></div> }
