import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { comicflowApi, type MediaProviderConfigView, type ProviderCapability, type ProviderProfilesView, type ProviderSlot } from '../api/client'

const labels = { text: '文本 / 剧本 API', image: '角色 / 场景图片 API', video: '视频 API' }
const slots = { test: '测试配置', production: '正式配置' }
const options = {
  text: [['bailian', '百炼 / 兼容 Chat Completions'], ['doubao', '火山方舟 / Doubao'], ['openai-compatible', 'OpenAI 兼容协议'], ['openrouter', 'OpenRouter'], ['custom', '自定义兼容文本协议']],
  image: [['bailian-image', '百炼万相异步图片'], ['openai-image', 'OpenAI 图片 (同步返回 Base64)']],
  video: [['bailian-video', '百炼万相视频'], ['compshare-h3', '优云 MiniMax H3'], ['xiangongyun-h3', '仙宫云 MiniMax H3']],
}
function defaults(capability: ProviderCapability, slot: ProviderSlot) {
  const wan = capability === 'video' && slot === 'test'
  return {
    provider: capability === 'text' ? 'bailian' : capability === 'image' ? 'bailian-image' : wan ? 'bailian-video' : 'compshare-h3',
    baseUrl: capability === 'text' ? 'https://dashscope.aliyuncs.com/compatible-mode/v1' : capability === 'image' || wan ? 'https://dashscope.aliyuncs.com/api/v1' : 'https://cp.compshare.cn',
    model: capability === 'text' ? 'qwen-plus' : capability === 'image' ? slot === 'test' ? 'wan2.2-t2i-flash' : 'wanx2.1-t2i-plus' : wan ? 'wan2.2-i2v-flash' : 'MiniMax-H3',
    enabled: false, timeoutMs: capability === 'text' ? 120000 : capability === 'image' ? 180000 : 600000,
    size: '720*1280', resolution: capability === 'video' && !wan ? '768P' : '480P', generationType: 'i2v',
    imageProtocol: 'auto', requestPath: '', statusPath: '',
    h3PromptMode: 'local-skill', inferenceProfile: 'turbo8_av_sol_gpu_te',
    submitPath: '/minimax/v2/video_generation', queryPath: '/minimax/v2/query/video_generation/{task_id}',
  }
}

export function LegacyModelApiSettings({ onClose }: { onClose: () => void }) {
  const client = useQueryClient()
  const config = useQuery({ queryKey: ['provider-config'], queryFn: comicflowApi.providerConfig })
  const refresh = () => client.invalidateQueries({ queryKey: ['provider-config'] })
  return <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
    <section className="model-dialog model-dialog-wide" role="dialog" aria-modal="true" aria-labelledby="model-dialog-title">
      <div className="model-dialog-head"><div><h2 id="model-dialog-title">模型 API 配置</h2><p>文本、图片、视频可分别切换测试与正式配置。保存和切换不会调用模型。</p></div><div className="model-dialog-head-actions">
        <button aria-label="刷新配置状态" onClick={() => void config.refetch()}><RefreshCw size={16} /></button><button aria-label="关闭" onClick={onClose}><X size={16} /></button>
      </div></div>
      <div className="model-dialog-note">文本、图片、视频模型名称均可自行填写，候选列表仅供参考。每次生成使用当前启用配置，不自动替换模型。配置仅在当前 API 进程内保存，重启后恢复环境配置；Worker 尚未同步。测试配置也可能计费，请在百炼控制台确认剩余额度并启用“免费额度用完即停”。</div>
      {config.error && <p role="alert">配置读取失败：{config.error.message}</p>}
      <div className="api-profile-list">
        {(['text', 'image', 'video'] as const).map(capability => <CapabilityProfiles key={capability} capability={capability} profiles={config.data?.profiles?.[capability]} current={config.data?.[capability]} runtime={config.data?.runtime} onSaved={refresh} />)}
        <article className="api-profile"><strong>提示词与输入方式</strong><p>H3 可选择本地英文 Skill 扩写，或中文输入交给优云 Context-IR 优化。两条路径互斥，不重复扩写。当前：{config.data?.runtime?.h3Prompt ?? '未读取'}。</p><small>百炼万相使用中文镜头描述，不额外调用文本扩写；基础图生视频只接收一张首帧图。视频时长沿用剧本，不随测试配置自动缩短。</small></article>
        <article className="api-profile"><strong>语音、口型与合成</strong><p>语音：{config.data?.runtime?.tts ?? '未读取'}；口型：{config.data?.runtime?.lipSync ?? '未读取'}；合成：{config.data?.runtime?.composition ?? '未读取'}。</p><small>这些能力仍通过服务器环境配置，尚未加入双配置切换。</small></article>
      </div>
      <div className="button-row"><button onClick={onClose}>完成</button></div>
    </section>
  </div>
}

function CapabilityProfiles({ capability, profiles, current, runtime, onSaved }: { capability: ProviderCapability; profiles?: ProviderProfilesView; current?: MediaProviderConfigView; runtime?: { imageAdapter?: string; imageModel?: string; imageProtocol?: string }; onSaved: () => Promise<void> }) {
  const [slot, setSlot] = useState<ProviderSlot>('production')
  const active = profiles?.active ?? 'production'
  const selected = profiles?.[slot] ?? (slot === active ? current : undefined)
  const imageRoute = capability === 'image' && runtime ? ` · 适配器：${runtime.imageAdapter ?? '未读取'} · 协议：${runtime.imageProtocol || '未读取'}` : ''
  return <article className="api-profile" aria-label={labels[capability]}>
    <div className="api-profile-header"><strong>{labels[capability]}</strong><span className="api-status">当前：{slots[active]} · {current?.enabled && current?.configured ? current.model : '未启用'}{imageRoute}</span></div>
    <label>编辑配置<select aria-label={`${capability}-编辑配置`} value={slot} onChange={event => setSlot(event.target.value as ProviderSlot)}>{Object.entries(slots).map(([value, title]) => <option key={value} value={value}>{title}</option>)}</select></label>
    <ProfileEditor key={slot} capability={capability} slot={slot} active={active === slot} remote={selected} runtime={runtime} onSaved={onSaved} />
  </article>
}

function ProfileEditor({ capability, slot, active, remote, runtime, onSaved }: { capability: ProviderCapability; slot: ProviderSlot; active: boolean; remote?: MediaProviderConfigView; runtime?: { imageAdapter?: string; imageModel?: string; imageProtocol?: string }; onSaved: () => Promise<void> }) {
  const [profile, setProfile] = useState(defaults(capability, slot))
  const [secret, setSecret] = useState('')
  const [dirty, setDirty] = useState(false)
  const [message, setMessage] = useState('')
  useEffect(() => {
    if (dirty) return
    const initial = defaults(capability, slot)
    setProfile({ ...initial, ...(remote?.provider ? remote : {}), resolution: remote?.resolution || initial.resolution })
  }, [remote, capability, slot, dirty])
  const update = (patch: Partial<typeof profile>) => { setProfile(value => ({ ...value, ...patch })); setDirty(true); setMessage('') }
  const savedKeyCompatible = Boolean(remote?.configured && remote.provider === profile.provider && remote.baseUrl === profile.baseUrl)
  const save = useMutation({
    mutationFn: () => {
      const common = { provider: profile.provider, baseUrl: profile.baseUrl, model: profile.model.trim(), timeoutMs: profile.timeoutMs, enabled: profile.enabled, ...(secret ? { apiKey: secret } : {}) }
      if (capability === 'text') return comicflowApi.saveProviderProfile(capability, slot, common)
      const mediaFields = { ...common, size: profile.size, submitPath: profile.submitPath, queryPath: profile.queryPath, imageProtocol: profile.imageProtocol, requestPath: profile.requestPath, statusPath: profile.statusPath }
      const payload = wan
        ? { ...mediaFields, resolution: profile.resolution, generationType: profile.generationType }
        : { ...mediaFields, resolution: profile.resolution, ...(capability === 'video' ? { h3PromptMode: profile.h3PromptMode, ...(profile.provider === 'xiangongyun-h3' ? { inferenceProfile: profile.inferenceProfile } : {}) } : {}) }
      return comicflowApi.saveProviderProfile(capability, slot, payload)
    },
    onSuccess: async () => { setSecret(''); setDirty(false); setMessage(`${slots[slot]}已保存${active ? '并生效' : '，尚未切换'}；未调用模型。`); await onSaved() },
  })
  const activate = useMutation({ mutationFn: () => comicflowApi.activateProviderProfile(capability, slot), onSuccess: async () => { setMessage(`已切换到${slots[slot]}；未调用模型。`); await onSaved() } })
  const clear = useMutation({ mutationFn: () => comicflowApi.deleteProviderProfile(capability, slot), onSuccess: async () => { setSecret(''); setDirty(false); setMessage('本套配置已清除，另一套配置保留。'); await onSaved() } })
  // The probe runs against the saved, in-effect configuration, so it is only
  // meaningful for the active slot with no unsaved edits. It sends one token and
  // calls no generation model -- the gate the acceptance plan asks for first.
  const testReady = capability === 'text' && active && !dirty && Boolean(remote?.configured)
  const test = useMutation({
    mutationFn: () => comicflowApi.testTextProviderConfig(),
    onSuccess: data => setMessage(`连通性正常：${data.model ?? '已连通'}；未调用生成模型。`),
    onError: () => setMessage(''),
  })
  const busy = save.isPending || activate.isPending || clear.isPending || test.isPending
  const wan = profile.provider === 'bailian-video'
  const models = capability === 'text' ? ['qwen-plus', 'qwen-turbo', 'Doubao-Seed-2.1-turbo', 'ep-xxxxxxxx'] : capability === 'image' ? ['wan2.2-t2i-flash', 'wanx2.1-t2i-turbo', 'wanx2.1-t2i-plus', 'wan2.6-image', 'image-2.5', 'gpt-image-2.5'] : wan ? ['wan2.2-i2v-flash', 'wanx2.1-i2v-turbo', 'wan2.6-i2v', 'wan2.7-t2v'] : ['MiniMax-H3']
  return <>
    <p>{slots[slot]}：{remote?.configured ? remote.enabled ? '已保存密钥，已启用' : '已保存密钥，但未启用' : '尚未保存密钥'}。更换供应商或服务域名需输入对应密钥；仅填写模型名不能适配另一种 API 协议。</p>
    <fieldset disabled={busy} style={{ border: 0, padding: 0, margin: 0 }}>
      <div className="api-profile-fields">
        <label>供应商<select value={profile.provider} onChange={event => {
          const provider = event.target.value
          setSecret('')
          update(provider === 'doubao' && capability === 'text'
            ? { provider, baseUrl: 'https://ark.cn-beijing.volces.com/api/v3', model: 'Doubao-Seed-2.1-turbo' }
            : { provider, ...(capability === 'video' ? { resolution: provider === 'compshare-h3' ? '768P' : provider === 'xiangongyun-h3' ? '0.5P' : '480P', h3PromptMode: provider === 'xiangongyun-h3' ? 'context-ir' : 'local-skill' } : {}) })
        }}>{options[capability].map(([value, title]) => <option key={value} value={value}>{title}</option>)}</select></label>
        <label>API 地址<input value={profile.baseUrl} onChange={event => update({ baseUrl: event.target.value })} /></label>
        <label>API Key<input type="password" autoComplete="off" value={secret} onChange={event => { setSecret(event.target.value); setDirty(true) }} placeholder={savedKeyCompatible ? '已保存，留空保留本套密钥' : '仅本次保存时提交'} /></label>
        <label>模型名称<input list={`${capability}-${slot}-models`} value={profile.model} onChange={event => update({ model: event.target.value })} /><datalist id={`${capability}-${slot}-models`}>{models.map(model => <option key={model} value={model} />)}</datalist></label>
        <label>超时（毫秒）<input type="number" min={1000} max={capability === 'text' ? 300000 : 900000} value={profile.timeoutMs} onChange={event => update({ timeoutMs: Number(event.target.value) })} /></label>
        {capability === 'image' && <label>图片尺寸<input value={profile.size} onChange={event => update({ size: event.target.value })} /></label>}
        {capability === 'video' && !wan && <>
          <label>H3 提示词处理<select value={profile.h3PromptMode} onChange={event => update({ h3PromptMode: event.target.value })}>
            <option value="local-skill">本地英文 Skill 扩写</option>
            <option value="context-ir">{profile.provider === 'xiangongyun-h3' ? '中文 Context-IR 本地编译' : '中文 + 优云提示词优化'}</option>
          </select></label>
          <small>{profile.h3PromptMode === 'context-ir'
            ? profile.provider === 'xiangongyun-h3' ? '本地编译中文镜头描述；仙宫云二次编译关闭，实际画质待开机验证。' : '中文剧本、动作、对白与参考图用途交给优云 Context-IR 优化；不调用本地文本扩写。生成仍可能计费，平台优化后的文本不可预览，实际画质待验证。'
            : '调用当前文本模型执行 H3 Skill，描述使用英文、对白保留原文；不开启平台二次优化。'}</small>
        </>}
        {capability === 'image' && <label>图片接口协议<select value={profile.imageProtocol} onChange={event => update({ imageProtocol: event.target.value })}><option value="auto">按已知模型匹配（不改模型名）</option><option value="wan-v2">万相文生图 V2 / 兼容接口</option><option value="wan26-image">万相 2.6 图文 / 兼容接口</option></select></label>}
        {(capability === 'image' || wan) && <>
          <label>自定义提交路径<input placeholder={capability === 'image' ? '留空使用所选图片协议默认路径' : '/services/aigc/video-generation/video-synthesis'} value={profile.requestPath} onChange={event => update({ requestPath: event.target.value })} /></label>
          <label>自定义查询路径<input placeholder="/tasks/{task_id}" value={profile.statusPath} onChange={event => update({ statusPath: event.target.value })} /></label>
        </>}
        {capability === 'video' && (wan ? <>
          <label>视频输入<select value={profile.generationType} onChange={event => update({ generationType: event.target.value })}><option value="i2v">图生视频（需要首帧）</option><option value="t2v">文生视频（需要对应 t2v 模型）</option></select></label>
          <label>视频分辨率<select value={profile.resolution} onChange={event => update({ resolution: event.target.value })}>{['480P', '720P', '1080P'].map(value => <option key={value}>{value}</option>)}</select></label>
        </> : profile.provider === 'xiangongyun-h3' ? <><label>仙宫云分辨率<select value={profile.resolution} onChange={event => update({ resolution: event.target.value })}>{['0.4P', '0.5P', '0.6P', '0.7P', '0.8P', '0.9P', '1.0P'].map(value => <option key={value}>{value}</option>)}</select></label><label>推理档位<select value={profile.inferenceProfile} onChange={event => update({ inferenceProfile: event.target.value })}><option value="turbo4_av_sol_gpu_te">极速</option><option value="turbo8_av_sol_gpu_te">平衡（默认）</option><option value="quality_av_sol_gpu_te">质量</option></select></label><small>默认 0.5P，9:16 为 544×960；提交时不再二次编译提示词。</small></> : <><label>视频分辨率<select value={profile.resolution} onChange={event => update({ resolution: event.target.value })}><option value="768P">768P（默认低成本档）</option><option value="1080P">1080P</option><option value="2K">2K</option></select></label><small>MiniMax H3 支持 768P、1080P 和 2K，默认使用低成本的 768P；不支持 720P。</small><label>提交路径<input value={profile.submitPath} onChange={event => update({ submitPath: event.target.value })} /></label><label>查询路径<input value={profile.queryPath} onChange={event => update({ queryPath: event.target.value })} /></label></>)}
      </div>
      <div className="api-profile-actions"><label><input type="checkbox" checked={profile.enabled} onChange={event => update({ enabled: event.target.checked })} />启用{capability === 'text' ? '文本' : capability === 'image' ? '图片' : '视频'} API</label>
        <button disabled={!profile.model.trim() || !profile.baseUrl || (profile.enabled && !secret && !savedKeyCompatible)} onClick={() => save.mutate()}>保存{capability === 'text' ? '文本' : capability === 'image' ? '图片' : '视频'}配置</button>
        {capability === 'text' && <button disabled={!testReady || test.isPending} onClick={() => test.mutate()}>测试文本连通性</button>}
        <button disabled={active || dirty || !remote?.provider} onClick={() => activate.mutate()}>{active ? '当前正在使用' : `切换使用${slots[slot]}`}</button>
        <button disabled={!remote?.provider} onClick={() => clear.mutate()}>清除本套配置</button>
      </div>
    </fieldset>
    {dirty && <small>修改尚未保存。先保存，再切换使用；当前套配置保存后立即生效。</small>}
    {capability === 'image' && <p>当前图片路由：{runtime?.imageAdapter ?? '未启用'} · {runtime?.imageModel || '无模型'} · {runtime?.imageProtocol || '无协议'}。模型名称只作为请求字段，不会自动切换 Provider。`image-2.5` 若使用 OpenAI 兼容图片接口，请选择“OpenAI 图片”；选择“百炼万相”仍会走万相协议。OpenAI 图片 Adapter 当前仅支持文生图，三视图图生图需要选择支持 `wan26-image` 的 Provider。</p>}
    {wan && <p>推荐流程测试：wan2.2-i2v-flash，480P，镜头时长 5 秒。时长需要在剧本中设置。wanx2.1-i2v-turbo 支持 3/4/5 秒；wan2.7-t2v 选择 720P 或 1080P。</p>}
    {capability === 'text' && profile.provider === 'doubao' && <p>火山方舟通常要求填写 Endpoint ID（例如 ep-...）；如果你的账号支持模型名，也可以保留 Doubao-Seed-2.1-turbo。API Key 只发送到后端，不会显示在配置回读中。</p>}
    {capability === 'text' && <p>「测试文本连通性」只发送一次单 token 请求，不触发生成；它检查的是当前生效的已保存配置，所以请先保存并切换使用再测试。检查失败会给出闭集原因（鉴权、模型未开通、限流、超时等），不必靠点一次生成去发现。</p>}
    {message && <p role="status">{message}</p>}
    {(save.error || activate.error || clear.error || test.error) && <p role="alert">{save.error?.message ?? activate.error?.message ?? clear.error?.message ?? test.error?.message}</p>}
  </>
}
