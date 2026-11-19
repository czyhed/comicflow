import { TextGenerationProgress, useTextGenerationProgress } from '../script/TextGenerationProgress'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, Film, ImagePlus, SlidersHorizontal, Sparkles, WandSparkles } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { comicflowApi } from '../../api/client'
import { useWorkspace } from '../../stores/workspace'
import { ScriptPreviewPanel } from '../script/ScriptPreviewPanel'
import { StylePresetPicker } from '../styles/StylePresetPicker'
import { speechBudget } from '../script/script-budget'
import type { GuidedSession, ReferenceImageAsset, Script, Shot, Snapshot, WorkflowMode } from '../../types'

function cloneScript(script: Script): Script {
  return JSON.parse(JSON.stringify(script)) as Script
}

type ScriptPreview = Awaited<ReturnType<typeof comicflowApi.previewScript>>

export function CreateWorkspace({ snapshot }: { snapshot?: Snapshot }) {
  const [story, setStory] = useState('暴雨夜的末班车上，失踪十年的姐姐突然在最后一排回头。')
  const [mode, setMode] = useState<WorkflowMode>('automatic')
  const [durationSec, setDurationSec] = useState('60')
  const [quality, setQuality] = useState('high')
  const [stylePresetId, setStylePresetId] = useState('')
  const [referenceName, setReferenceName] = useState<string | null>(null)
  const [referenceFile, setReferenceFile] = useState<File | null>(null)
  const [referenceAsset, setReferenceAsset] = useState<ReferenceImageAsset | undefined>(snapshot?.project.referenceImage ?? undefined)
  const [draftScript, setDraftScript] = useState<Script | undefined>(snapshot?.script)
  const [draftVersion, setDraftVersion] = useState<number | undefined>(snapshot?.project.version)
  const [draftDirty, setDraftDirty] = useState(false)
  const [storyText, setStoryText] = useState<string | undefined>(snapshot?.project.generatedStoryText ?? undefined)
  const [storyTextDirty, setStoryTextDirty] = useState(false)
  const [guided, setGuided] = useState<GuidedSession | undefined>(snapshot?.project.generationSession?.guided)
  const [answer, setAnswer] = useState('')
  const [generationPhase, setGenerationPhase] = useState('等待开始')
  const progress = useTextGenerationProgress()
  const [scriptPreview, setScriptPreview] = useState<ScriptPreview>()
  const guidanceStarted = useRef(false)
  const { setProjectId, setActiveModule } = useWorkspace()
  const queryClient = useQueryClient()
  const generate = useMutation({
    mutationFn: async () => {
      const created = await comicflowApi.createProject({ story, durationSec: Number(durationSec), mode,
        ...(stylePresetId ? { stylePresetId } : {}) })
      if (mode === 'automatic') {
        const generated = await comicflowApi.generateStoryText(created.project.id, progress.receive)
        return { created, generated, kind: 'story' as const }
      }
      if (mode === 'guided') {
        const generated = await comicflowApi.generateScript(created.project.id)
        return { created, generated, kind: 'script' as const }
      }
      const generated = await comicflowApi.previewScript(created.project.id, progress.receive)
      return { created, generated, kind: 'script-preview' as const }
    },
    onMutate: () => {
      setGenerationPhase(mode === 'automatic' ? '准备扩写故事…' : '正在拆分你的内容…')
      guidanceStarted.current = false
      setGuided(undefined)
      setAnswer('')
      setDraftScript(undefined)
      setDraftVersion(undefined)
      setDraftDirty(false)
      setStoryText(undefined)
      setScriptPreview(undefined)
      progress.reset()
      setStoryTextDirty(false)
    },
    onSuccess: ({ created, generated, kind }) => {
      setProjectId(created.project.id)
      setGenerationPhase('生成完成')
      if (kind === 'story') {
        setDraftVersion(generated.project.version)
        setStoryText(generated.storyText)
      } else if (kind === 'script-preview') {
        setScriptPreview(generated)
      } else {
        setDraftVersion(generated.project.version)
        setDraftScript(cloneScript(generated.script))
      }
      setDraftDirty(false)
      setGuided(created.project.generationSession?.guided)
      if (referenceFile) uploadReference.mutate(referenceFile)
      void queryClient.invalidateQueries({ queryKey: ['snapshot', created.project.id] })
    },
  })
  const persistedMode = generate.data?.created.project.input?.mode
    ?? snapshot?.project.input?.mode
    ?? snapshot?.project.generationSession?.mode
  useEffect(() => {
    if (generate.isPending || !persistedMode) return
    setMode(persistedMode)
  }, [persistedMode, generate.isPending])
  useEffect(() => {
    if (!generate.isPending && !storyTextDirty && snapshot?.project.generatedStoryText) setStoryText(snapshot.project.generatedStoryText)
    if (!generate.isPending && snapshot?.project.referenceImage) setReferenceAsset(snapshot.project.referenceImage)
    if (!generate.isPending && !draftDirty && snapshot?.script && snapshot.project.version >= (draftVersion ?? 0)) {
      setDraftVersion(snapshot.project.version)
      setDraftScript(cloneScript(snapshot.script))
    }
    if (!generate.isPending && !guided && snapshot?.project.generationSession?.guided) setGuided(snapshot.project.generationSession.guided)
  }, [snapshot?.project.id, snapshot?.project.input?.mode, snapshot?.project.generationSession?.mode, snapshot?.project.version, snapshot?.script, snapshot?.project.generatedStoryText, snapshot?.project.generationSession?.guided, draftDirty, draftVersion, guided, storyTextDirty, generate.isPending])
  const generatedScript: Script | undefined = generate.isPending ? undefined : (draftScript ?? (generate.data?.kind === 'script' ? generate.data.generated.script : undefined) ?? snapshot?.script)
  const generatedDuration = generatedScript?.shots.reduce((total, shot) => total + shot.durationSec, 0) ?? 0
  const projectId = generate.data?.created.project.id ?? snapshot?.project.id
  const version = draftVersion ?? (generate.data?.kind === 'story' || generate.data?.kind === 'script' ? generate.data.generated.project.version : undefined) ?? snapshot?.project.version ?? 1
  // Two different questions, deliberately kept apart:
  //   `mode`       — what the user has selected for the NEXT generation. Drives the
  //                  composer: the radio, the action button, and the request itself.
  //   `activeMode` — what the LOADED project actually is. Drives how its results are
  //                  rendered, and must not follow a stale local radio selection.
  // Conflating them caused both the automatic-mode stall (results hidden because the
  // radio disagreed with the project) and, in the other direction, a frozen radio.
  const activeMode = generate.isPending ? mode : (persistedMode ?? mode)
  const uploadReference = useMutation({
    mutationFn: async (file: File) => {
      if (!projectId) throw new Error('PROJECT_REQUIRED')
      return comicflowApi.uploadReferenceImage(projectId, file)
    },
    onSuccess: (result) => {
      setReferenceAsset(result.asset)
      setDraftVersion(result.projectVersion)
      setReferenceFile(null)
      void queryClient.invalidateQueries({ queryKey: ['snapshot', projectId] })
    },
  })
  const saveDraft = useMutation({
    mutationFn: () => {
      if (!projectId || !generatedScript) throw new Error('PROJECT_REQUIRED')
      return comicflowApi.updateScript(projectId, generatedScript, version)
    },
    onSuccess: (result) => {
      setDraftVersion(result.project.version)
      setDraftScript(cloneScript(result.script))
      setDraftDirty(false)
      void queryClient.invalidateQueries({ queryKey: ['snapshot', projectId] })
    },
  })
  const confirmScriptPreview = useMutation({
    mutationFn: () => {
      if (!projectId || !scriptPreview) throw new Error('PROJECT_REQUIRED')
      return comicflowApi.commitScriptPreview(projectId, scriptPreview)
    },
    onSuccess: (result) => {
      setScriptPreview(undefined)
      setDraftVersion(result.project.version)
      setDraftScript(cloneScript(result.script))
      queryClient.setQueryData(['snapshot', projectId], (current: Snapshot | undefined) => current ? { ...current, project: result.project, script: result.script } : { project: result.project, script: result.script, jobs: [], creditLedger: [], visualAssets: [], audioAssets: [], lipSyncAssets: [], timelines: {} })
      void queryClient.invalidateQueries({ queryKey: ['snapshot', projectId] })
      setActiveModule('script')
    },
  })
  const saveStoryText = useMutation({
    mutationFn: () => {
      if (!projectId || !storyText) throw new Error('STORY_TEXT_REQUIRED')
      return comicflowApi.updateStoryText(projectId, storyText, version)
    },
    onSuccess: (result) => {
      setStoryText(result.storyText)
      setDraftVersion(result.project.version)
      setStoryTextDirty(false)
      void queryClient.invalidateQueries({ queryKey: ['snapshot', projectId] })
    },
  })
  const askQuestion = useMutation({
    mutationFn: () => {
      if (!projectId) throw new Error('PROJECT_REQUIRED')
      return comicflowApi.askGuidedQuestion(projectId)
    },
    onSuccess: (result) => setGuided(result.guided),
  })
  useEffect(() => {
    if (generate.isPending || activeMode !== 'guided' || !projectId || !generatedScript || guidanceStarted.current) return
    if (guided?.done || guided?.currentQuestion) return
    guidanceStarted.current = true
    askQuestion.mutate()
  }, [activeMode, projectId, generatedScript, guided, askQuestion, generate.isPending])
  const answerQuestion = useMutation({
    mutationFn: () => {
      if (!projectId) throw new Error('PROJECT_REQUIRED')
      return comicflowApi.answerGuidedQuestion(projectId, answer)
    },
    onSuccess: (result) => { setGuided(result.guided); setAnswer('') },
  })
  const skipQuestion = useMutation({
    mutationFn: () => {
      if (!projectId) throw new Error('PROJECT_REQUIRED')
      return comicflowApi.skipGuidedQuestion(projectId)
    },
    onSuccess: (result) => setGuided(result.guided),
  })
  const detail = useMutation({
    mutationFn: async () => {
      if (!projectId) throw new Error('PROJECT_REQUIRED')
      if (draftDirty && generatedScript) await comicflowApi.updateScript(projectId, generatedScript, version)
      return comicflowApi.generateDetailedScript(projectId)
    },
    onSuccess: (result) => { setDraftVersion(result.project.version); setDraftScript(cloneScript(result.script)); setDraftDirty(false); setGuided((current) => current ? { ...current, done: true, currentQuestion: '' } : current); void queryClient.invalidateQueries({ queryKey: ['snapshot', projectId] }) },
  })
  const activeGuided: GuidedSession = guided ?? { questionCount: 0, maxQuestions: 9, currentQuestion: '', transcript: [], done: false }
  const hasDetailedScript = Boolean(detail.data?.script || guided?.detailGenerated || snapshot?.project.generationSession?.guided?.detailGenerated)
  const showGuidedChat = Boolean(generatedScript && activeMode === 'guided' && !activeGuided.done && !hasDetailedScript && !askQuestion.isError)
  const showGuidedComplete = Boolean(generatedScript && activeMode === 'guided' && activeGuided.done && !hasDetailedScript && !askQuestion.isError)
  const retryGuidance = () => {
    if (!projectId) return
    guidanceStarted.current = true
    askQuestion.mutate()
  }
  const updateShot = (shotId: string, patch: Partial<Shot>) => {
    setDraftScript((current) => current ? { ...current, shots: current.shots.map((shot) => shot.id === shotId ? { ...shot, ...patch } : shot) } : current)
    setDraftDirty(true)
  }
  const openScriptModule = () => {
    if (storyTextDirty) {
      void saveStoryText.mutateAsync().then(() => setActiveModule('script'))
      return
    }
    setActiveModule('script')
  }
  return (
    <section className="generation-studio">
      <div className="studio-controls">
        <div className="studio-tabs"><span className="active">故事生成</span></div>
        <div className="model-select"><Sparkles size={16} /><span>文本模型按用途配置，请在顶部“模型 API”中查看或切换。</span></div>
        <div className="prompt-panel">
          <div className="panel-title"><div><WandSparkles size={18} /><span><strong>描述你的故事</strong><small>输入故事、灵感或人物关系</small></span></div><span>{story.length} / 2,000</span></div>
          <label className="reference-upload" htmlFor="reference-image"><ImagePlus size={19} /><span>{referenceName ?? referenceAsset?.filename ?? '添加参考图'}</span><small>{uploadReference.isPending ? '正在上传参考图…' : referenceAsset ? '参考图已保存，剧本阶段暂不参与' : '可选 · 剧本阶段暂不参与，后续画面生成使用'}</small><input id="reference-image" aria-label="添加参考图" type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => { const file = event.target.files?.[0] ?? null; setReferenceFile(file); setReferenceName(file?.name ?? null); if (file && projectId) uploadReference.mutate(file) }} /></label>
          {uploadReference.error && <div className="error-banner" role="alert">参考图上传失败：{(uploadReference.error as Error).message}</div>}
          <textarea value={story} onChange={(event) => setStory(event.target.value)} maxLength={2000} />
          <div className="studio-hint">例如：暴雨夜的末班车上，失踪十年的姐姐突然在最后一排回头。</div>
          <div className="mode-row"><label><input type="radio" checked={mode === 'automatic'} onChange={() => setMode('automatic')} /><span><strong>全自动生成</strong><small>从故事灵感生成可编辑文本</small></span></label><label><input type="radio" checked={mode === 'import_story' || mode === 'import_script'} onChange={() => setMode('import_story')} /><span><strong>导入内容并整理</strong><small>粘贴已有故事或剧本，自动解析为可编辑剧本</small></span></label></div>
          {generate.error && <div className="error-banner" role="alert">{generate.error.message}</div>}
          <div className="studio-options"><label><Film size={14} /> 视频时长<select aria-label="视频时长" value={durationSec} onChange={(event) => setDurationSec(event.target.value)}><option value="30">30 秒</option><option value="60">60 秒</option><option value="90">90 秒</option></select></label><label><SlidersHorizontal size={14} /> 输出质量<select aria-label="输出质量" value={quality} onChange={(event) => setQuality(event.target.value)}><option value="standard">标准</option><option value="high">高质量</option></select></label></div>
          <StylePresetPicker value={stylePresetId} onChange={setStylePresetId} disabled={generate.isPending}
            saved={snapshot?.project.visualStyleProfile} hasProject={Boolean(snapshot?.project)} />
          <button className="primary-command" disabled={story.trim().length < 10 || generate.isPending} onClick={() => generate.mutate()}>{generate.isPending ? '正在处理…' : mode === 'automatic' ? '生成故事文本' : '拆分为剧本'} <ArrowRight size={17} /></button>
        </div>
        <div className="studio-footnote">内容由 AI 生成，请遵守相关法律法规</div>
      </div>
      <div className="studio-gallery">
        <div className="gallery-toolbar"><span>生成资产</span><small>剧本和镜头将在生成后自动整理</small></div>
        {generate.isPending ? (
          <article className="generation-progress" role="status" aria-live="polite">
            <div className="guided-chat-head"><span className="eyebrow">AI 生成中</span><strong>{generationPhase}</strong><small>正在整理内容，完成后会自动显示可编辑结果。</small></div>
            <div className="generation-progress-track"><span /></div>
            <TextGenerationProgress {...progress} kind={mode === 'automatic' ? 'story' : 'script'} />
          </article>
        ) : storyText && !generatedScript && activeMode === 'automatic' ? (
          <article className="story-text-preview">
            <div className="guided-chat-head"><span className="eyebrow">故事已就绪</span><strong>故事文本已生成</strong><small>先修改文本，确认后到剧本模块拆分场景与镜头。</small></div>
            <label className="preview-field">生成的故事文本<textarea aria-label="生成的故事文本" value={storyText} onChange={(event) => { setStoryText(event.target.value); setStoryTextDirty(true) }} /></label>
            {(saveStoryText.error || generate.error) && <div className="error-banner" role="alert">{(saveStoryText.error as Error | null)?.message ?? (generate.error as Error).message}</div>}
            <div className="script-preview-footer"><button className="script-preview-save" onClick={() => saveStoryText.mutate()} disabled={!storyTextDirty || saveStoryText.isPending}>{saveStoryText.isPending ? '保存中…' : '保存故事文本'}</button><button className="script-preview-open" onClick={openScriptModule} disabled={saveStoryText.isPending}>{storyTextDirty ? '保存并进入剧本模块' : '进入剧本模块拆分'} <ArrowRight size={14} /></button></div>
          </article>
        ) : showGuidedChat ? (
          <article className="guided-chat">
            <div className="guided-chat-head"><span className="eyebrow">剧情问答</span><strong>一起完善你的剧情</strong><small>最多 {activeGuided.maxQuestions} 轮，模型会在信息足够时提前结束。</small></div>
            <div className="chat-messages">
              <div className="chat-bubble user"><small>你的故事</small><p>{story}</p></div>
              <div className="chat-bubble assistant"><small>AI 剧情助手 · 已收到</small><p>故事已收到，我们先用几个简短问题把剧情方向确定下来。</p></div>
              {activeGuided.transcript.map((item, index) => <div className="chat-turn" key={`${item.question}-${index}`}><div className="chat-bubble assistant"><small>AI 剧情助手</small><p>{item.question}</p></div><div className="chat-bubble user"><small>你的回答</small><p>{item.answer}</p></div></div>)}
              {activeGuided.currentQuestion && <div className="chat-bubble assistant"><small>AI 剧情助手 · 第 {activeGuided.questionCount + 1} / {activeGuided.maxQuestions} 轮</small><p>{activeGuided.currentQuestion}</p></div>}
            </div>
            <div className="chat-composer"><textarea aria-label="你的回答" value={answer} maxLength={400} onChange={(event) => setAnswer(event.target.value)} placeholder="用一两句话回答" /><div className="chat-composer-actions"><span>{answer.length} / 400</span><button onClick={() => answerQuestion.mutate()} disabled={!answer.trim() || answer.length > 400 || answerQuestion.isPending}>发送回答</button><button className="chat-skip" onClick={() => skipQuestion.mutate()} disabled={skipQuestion.isPending || answerQuestion.isPending}>跳过此问题</button><button className="chat-skip" onClick={() => detail.mutate()} disabled={detail.isPending}>直接生成当前剧本</button></div></div>
          </article>
        ) : showGuidedComplete ? (
          <article className="guided-chat guided-complete"><div className="guided-chat-head"><span className="eyebrow">下一步</span><strong>剧情方向已收束</strong><small>已完成 {activeGuided.questionCount} 轮确认，可以进入下一步生成完整剧本。</small></div><button className="script-preview-next" onClick={() => detail.mutate()} disabled={detail.isPending}>{detail.isPending ? '正在生成完整剧本…' : '下一步：生成完整剧本'} <ArrowRight size={14} /></button></article>
        ) : scriptPreview ? (
          <ScriptPreviewPanel preview={scriptPreview} pending={confirmScriptPreview.isPending} error={confirmScriptPreview.error}
            onCancel={() => { setScriptPreview(undefined); confirmScriptPreview.reset() }} onConfirm={() => confirmScriptPreview.mutate()} />
        ) : generatedScript ? (
          <article className={`script-preview${activeMode === 'automatic' ? ' script-preview-automatic' : ''}`}>
            <div className="script-preview-head">
              <div className="script-preview-status"><span className="eyebrow">{activeMode === 'automatic' ? '自动生成' : '剧本初稿'}</span>{activeMode === 'automatic' && <span className="script-ready-status">全自动生成完成</span>}</div>
              <strong className="preview-title-display">{generatedScript.title}</strong>
              <label className="preview-field preview-title-field">剧本标题<input aria-label="剧本标题" value={generatedScript.title} onChange={(event) => { setDraftScript({ ...generatedScript, title: event.target.value }); setDraftDirty(true) }} /></label>
              <small>{generatedScript.scenes.length} 个场景 · {generatedScript.shots.length} 个镜头 · {generatedDuration} 秒</small>
              {activeMode === 'automatic' && <div className="script-overview" aria-label="剧本概览"><span><strong>{generatedScript.scenes.length} 个</strong><small>场景</small></span><span><strong>{generatedScript.shots.length} 个</strong><small>镜头</small></span><span><strong>{generatedDuration} 秒</strong><small>总时长</small></span></div>}
            </div>
            {generatedScript.scenes[0] && <label className="preview-field">场景标题<input aria-label="场景标题" value={generatedScript.scenes[0].title} onChange={(event) => { setDraftScript({ ...generatedScript, scenes: generatedScript.scenes.map((scene, index) => index === 0 ? { ...scene, title: event.target.value } : scene) }); setDraftDirty(true) }} /></label>}
            <div className="script-preview-list">
              {generatedScript.shots.map((shot, index) => (
                <div className="script-preview-shot" key={shot.id}>
                  {(() => {
                    const budget = speechBudget(shot)
                    return <div className="draft-shot-head">
                      <span className="shot-index">{String(shot.order ?? index + 1).padStart(2, '0')}</span>
                      <label className="preview-field draft-shot-title">镜头标题<input aria-label={`镜头标题-${shot.id}`} value={shot.title} onChange={(event) => updateShot(shot.id, { title: event.target.value })} /></label>
                      <div className="shot-preview-meta"><span>{shot.shotSize}</span><span>{shot.durationSec}s</span><span>{shot.emotion}</span>
                        {budget.status !== 'silent' && <span className={`speech-badge ${budget.status}`} title="按每秒约 4 字、预留 1 秒动作反应估算">台词 {budget.used}/{budget.limit}</span>}</div>
                    </div>
                  })()}
                  <div className="draft-shot-body">
                    <div>
                      <label className="preview-field">画面描述<textarea aria-label={`画面描述-${shot.id}`} value={shot.visualDescription} onChange={(event) => updateShot(shot.id, { visualDescription: event.target.value })} /></label>
                      <label className="preview-field">动作<input aria-label={`动作-${shot.id}`} value={shot.action} onChange={(event) => updateShot(shot.id, { action: event.target.value })} /></label>
                    </div>
                    <div>
                      <label className="preview-field">对白<textarea aria-label={`对白-${shot.id}`} placeholder="无对白可留空" value={shot.dialogue} onChange={(event) => updateShot(shot.id, { dialogue: event.target.value })} /></label>
                      <label className="preview-field">旁白<textarea aria-label={`旁白-${shot.id}`} placeholder="无旁白可留空" value={shot.narration} onChange={(event) => updateShot(shot.id, { narration: event.target.value })} /></label>
                    </div>
                  </div>
                </div>
              ))}
            </div>
            {saveDraft.error && <div className="error-banner" role="alert">{(saveDraft.error as Error).message}</div>}
            {detail.error && <div className="error-banner" role="alert">{(detail.error as Error).message}</div>}
            {askQuestion.error && <div className="error-banner" role="alert">问答暂时不可用：{(askQuestion.error as Error).message}<button onClick={retryGuidance}>重试问答</button></div>}
            <div className="script-preview-footer"><button className="script-preview-save" onClick={() => saveDraft.mutate()} disabled={!draftDirty || saveDraft.isPending}>保存剧本草稿</button><button className="script-preview-open" onClick={() => setActiveModule('script')}>打开剧本编辑器 <ArrowRight size={14} /></button></div>
          </article>
        ) : (
          <div className="gallery-empty"><Sparkles size={42} /><strong>你的创作会出现在这里</strong><span>生成故事后，剧本和镜头资产将自动整理</span></div>
        )}
      </div>
    </section>
  )
}
