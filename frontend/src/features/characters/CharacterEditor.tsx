import { useMutation } from '@tanstack/react-query'
import { Save } from 'lucide-react'
import { useState } from 'react'
import { CharacterReferences, useCharacterReferenceActions } from './CharacterReferences'
import { comicflowApi } from '../../api/client'
import type { CharacterCard, CharacterPromptPreview, CharacterPromptPurpose, CharacterSettingField, Snapshot } from '../../types'

const settingFields: CharacterSettingField[] = ['appearance', 'clothing', 'personality']
const fieldLabels = { appearance: '外观', clothing: '服装', personality: '性格', referenceImagePrompt: '参考图提示词' }

export function CharacterEditor({ card, snapshot, onSaved, refresh }: {
  card?: CharacterCard
  snapshot: Snapshot
  onSaved: (card: CharacterCard) => Promise<void>
  refresh: () => Promise<void>
}) {
  const [draft, setDraft] = useState<Omit<CharacterCard, 'id'>>(card ?? {
    name: '', appearance: '', clothing: '', personality: '', voice: { language: 'zh-CN' },
  })
  const [saved, setSaved] = useState(false)
  const [assistantOpen, setAssistantOpen] = useState(!card?.appearance || !card?.clothing)
  const [instructions, setInstructions] = useState('')
  const [purpose, setPurpose] = useState<CharacterPromptPurpose>(card?.appearance && card.clothing ? 'reference-image' : 'settings')
  const [outputFields, setOutputFields] = useState<CharacterSettingField[]>(() => {
    const missing = settingFields.filter(field => !card?.[field]?.trim())
    return missing.length ? missing : [...settingFields]
  })
  const [preview, setPreview] = useState<CharacterPromptPreview | null>(null)
  const [adoptedVersion, setAdoptedVersion] = useState<number | null>(null)
  const update = (patch: Partial<typeof draft>) => { setDraft((value) => ({ ...value, ...patch })); setSaved(false); setPreview(null) }
  const prompt = useMutation({
    mutationFn: () => comicflowApi.previewCharacterPrompt(snapshot.project.id, {
      characterId: card?.id, expectedVersion: snapshot.project.version,
      expectedRevision: draft.revision ?? 0, instructions,
      purpose, ...(purpose === 'settings' ? { outputFields } : {}),
      fields: { name: draft.name, appearance: draft.appearance, clothing: draft.clothing, personality: draft.personality, referenceImagePrompt: draft.referenceImagePrompt ?? '' },
    }),
    onSuccess: setPreview,
    retry: false,
  })
  const save = useMutation({
    mutationFn: () => comicflowApi.saveProjectCharacter(snapshot.project.id, draft, card?.id, adoptedVersion ?? snapshot.project.version),
    onSuccess: async (result) => { setDraft(result); setSaved(true); setPreview(null); setAdoptedVersion(null); await onSaved(result) },
  })
  const assign = useMutation({
    mutationFn: ({ shotId, checked }: { shotId: string; checked: boolean }) => {
      const ids = snapshot.script?.shots.find((shot) => shot.id === shotId)?.characterIds ?? []
      return comicflowApi.assignShotCharacters(snapshot.project.id, shotId, checked ? [...ids, card!.id] : ids.filter((id) => id !== card!.id), snapshot.project.version)
    },
    onSuccess: refresh,
  })
  const references = useCharacterReferenceActions(snapshot, card, refresh)
  const hasReferenceImage = Boolean(card?.referenceImageUrl && card.referenceImageMediaType === 'image')
  const unsaved = !card || (['name', 'appearance', 'clothing', 'personality', 'referenceImagePrompt'] as const).some((field) => (draft[field] ?? '') !== (card[field] ?? '')) || draft.voice.voiceId !== card.voice.voiceId
  const busy = prompt.isPending || save.isPending || references.busy
  const canPolish = Boolean(draft.appearance.trim() && draft.clothing.trim())
  return <>
    <section className="character-stage">
      <div className="editor-toolbar"><strong>{card?.name ?? '新角色'}</strong><span>{card?.referenceBoard?.status === 'approved' ? '已确认角色设定板' : hasReferenceImage ? '已生成参考图' : '参考图尚未生成'}</span></div>
      <CharacterReferences card={card} actions={references} unsaved={unsaved} busy={busy} />
      <details className="character-prompt-assistant character-fold" open={assistantOpen} onToggle={event => setAssistantOpen(event.currentTarget.open)}>
        <summary>角色提示词助手（可选）</summary>
        <p>使用 API 管理中的文本模型生成中文草稿，每次点击可能计费。只修改本次选择的内容；生成图片需另行点击。</p>
        <label>本次处理<select aria-label="角色提示词用途" disabled={busy} value={purpose} onChange={event => {
          setPurpose(event.target.value as CharacterPromptPurpose); setPreview(null); prompt.reset()
        }}>
          <option value="settings">完善角色设定</option>
          <option value="reference-image">仅润色主图提示词</option>
        </select></label>
        {purpose === 'settings' ? <>
          <p>结合已保存故事与出场镜头，只生成勾选字段。其余设定和已有图片提示词保留。</p>
          <div className="button-row">{settingFields.map(field => <label key={field}>
            <input type="checkbox" aria-label={`生成设定-${fieldLabels[field]}`} disabled={busy} checked={outputFields.includes(field)} onChange={event => {
              setOutputFields(values => event.target.checked ? [...values, field] : values.filter(value => value !== field)); setPreview(null)
            }} />{fieldLabels[field]}
          </label>)}</div>
        </> : <p>保留已有外观和服装，只润色主图的材质、光影与构图。按项目画风生成清晰的角色参考图描述，不带入剧情场景。</p>}
        <label>补充要求（选填）<textarea aria-label="角色提示词补充要求" maxLength={2000} disabled={busy} value={instructions} placeholder="例如：保留蓝色外套，突出棉布材质和清晰五官" onChange={(event) => { setInstructions(event.target.value); setPreview(null) }} /></label>
        <button disabled={busy || !draft.name.trim() || (purpose === 'settings' ? !outputFields.length : !canPolish)} onClick={() => { setPreview(null); prompt.mutate() }}>{prompt.isPending ? '正在生成草稿…' : purpose === 'settings' ? '生成所选角色设定' : '润色主图提示词'}</button>
        {!draft.name.trim() && <p>请先填写角色名称。</p>}
        {purpose === 'settings' && !outputFields.length && <p>请至少选择一个设定字段。</p>}
        {purpose === 'reference-image' && !canPolish && <p>请先填写外观与服装，或切换到“完善角色设定”。</p>}
        {prompt.error && <p role="alert">提示词生成失败：{prompt.error.message}</p>}
        {preview && <section className="character-prompt-preview" aria-label="角色提示词草稿">
          <h4>生成草稿 · 尚未保存</h4>
          <p>核对并修改下方草稿，再采用到编辑区。未展示的字段保持原值，保存后才用于下一次生成。</p>
          {(['appearance', 'clothing', 'personality', 'referenceImagePrompt'] as const).filter(field => preview.draft[field] !== undefined).map((field) => {
            const label = fieldLabels[field]
            return <label key={field}>{label}<textarea aria-label={`草稿-${label}`} maxLength={field === 'referenceImagePrompt' ? 4000 : 2000} value={preview.draft[field]} onChange={(event) => setPreview({ ...preview, draft: { ...preview.draft, [field]: event.target.value } })} /></label>
          })}
          <div className="button-row">
            <button disabled={busy || preview.expectedVersion !== snapshot.project.version || !Object.values(preview.draft).every((value) => value?.trim())} onClick={() => {
              setDraft((value) => ({ ...value, ...preview.draft, revision: preview.expectedRevision ?? 0 }))
              setAdoptedVersion(preview.expectedVersion)
              setSaved(false); setPreview(null)
            }}>采用草稿到编辑区</button>
            <button onClick={() => setPreview(null)}>放弃草稿</button>
          </div>
          {preview.expectedVersion !== snapshot.project.version && <p role="alert">剧本已更新，请基于新版本重新生成草稿。</p>}
        </section>}
      </details>
      <details className="character-bindings character-fold"><summary>出场镜头与绑定</summary>
      {card ? snapshot.script?.shots.map((shot) => <label key={shot.id} className="character-shot-binding">
        <input type="checkbox" checked={shot.characterIds?.includes(card.id) ?? false} disabled={assign.isPending || busy} onChange={(event) => assign.mutate({ shotId: shot.id, checked: event.target.checked })} /> {shot.order}. {shot.title}
      </label>) : <p>保存角色后可绑定镜头。</p>}
      {assign.error && <p role="alert">绑定失败：{assign.error.message}</p>}
      </details>
    </section>
    <aside className="inspector">
      <div className="inspector-head"><strong>角色属性</strong><span>{saved ? '已保存' : '可编辑'}</span></div>
      {(['name', 'appearance', 'clothing', 'personality'] as const).map((field) => <label key={field}>{({ name: '角色名称', appearance: '外观设定', clothing: '服装', personality: '性格' })[field]}<textarea aria-label={`角色-${field}`} disabled={busy} maxLength={field === 'name' ? 100 : 2000} value={draft[field]} onChange={(event) => update({ [field]: event.target.value })} /></label>)}
      <details className="character-fold"><summary>单张主图提示词（选填）</summary>
      <label>角色参考图提示词<textarea aria-label="角色参考图提示词" disabled={busy} maxLength={4000} value={draft.referenceImagePrompt ?? ''} onChange={(event) => update({ referenceImagePrompt: event.target.value })} /></label>
      <p className="inspector-note">主图生成使用此提示词；文字设定板使用外观、服装和项目风格。只修改提示词会保留已确认图片；修改外观或服装后请核对素材，旧设定板会失效。</p>
      </details>
      <details className="character-fold"><summary>声音设置（选填）</summary>
      <label>声音标识（选填）<input aria-label="角色声音" disabled={busy} value={draft.voice.voiceId ?? ''} onChange={(event) => update({ voice: { ...draft.voice, language: 'zh-CN', voiceId: event.target.value } })} /></label>
      </details>
      <button className="full-command" disabled={busy || ![draft.name, draft.appearance, draft.clothing, draft.personality].every((value) => value.trim())} onClick={() => save.mutate()}><Save size={15} />{save.isPending ? '保存中…' : '保存角色设定'}</button>
      {save.error && <p role="alert">保存失败：{save.error.message}</p>}
    </aside>
  </>
}
