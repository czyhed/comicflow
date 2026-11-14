import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, Pencil, Plus, RefreshCw, Trash2, X } from 'lucide-react'
import { useState } from 'react'
import { modelRegistry, type ConnectionTestResult, type ModelCatalog, type ModelConnection, type RegistryModel } from '../api/modelRegistry'
import { LegacyModelApiSettings } from './LegacyModelApiSettings'

type Editor = { kind: 'connections'; value?: ModelConnection } | { kind: 'models'; value?: RegistryModel; copy?: boolean }

export function ModelApiSettings({ onClose }: { onClose: () => void }) {
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['model-registry'], queryFn: modelRegistry.read })
  const [tab, setTab] = useState<'models' | 'connections' | 'bindings'>('models')
  const [editor, setEditor] = useState<Editor | null>(null)
  const [legacy, setLegacy] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null)
  const [pendingDelete, setPendingDelete] = useState<{ kind: 'models' | 'connections'; id: string } | null>(null)
  const data = query.data
  const update = async (value: ModelCatalog) => {
    client.setQueryData(['model-registry'], value)
    await client.invalidateQueries({ queryKey: ['provider-config'] })
  }
  const act = async (operation: () => Promise<ModelCatalog>, success: string) => {
    setBusy(true); setError(''); setMessage('')
    try { await update(await operation()); setMessage(success); setPendingDelete(null) }
    catch (cause) { setError(cause instanceof Error ? cause.message : '操作失败') }
    finally { setBusy(false) }
  }
  if (legacy) return <LegacyModelApiSettings onClose={onClose} />
  return <div className="modal-backdrop">
    <section className="model-dialog registry-dialog" role="dialog" aria-modal="true" aria-labelledby="registry-title">
      <header className="model-dialog-head">
        <div><h2 id="registry-title">模型管理</h2><p>配置一次，按用途选用。保存、切换和预览不调用模型。</p></div>
        <div className="model-dialog-head-actions">
          <button aria-label="刷新模型库" onClick={() => void query.refetch()}><RefreshCw size={17} /></button>
          <button aria-label="关闭模型管理" onClick={onClose}><X size={20} /></button>
        </div>
      </header>
      <nav className="registry-tabs" aria-label="模型管理分类">
        {([['models', '模型列表'], ['connections', '连接与密钥'], ['bindings', '用途选择']] as const).map(([key, name]) =>
          <button key={key} aria-pressed={tab === key} onClick={() => { setTab(key); setPreview(null); setPendingDelete(null) }}>{name}</button>)}
      </nav>
      <button className="registry-legacy" onClick={() => setLegacy(true)}>查看旧双槽配置</button>
      {query.isLoading && <p>正在读取模型配置…</p>}
      {(query.error || error) && <p className="registry-error" role="alert">{error || query.error?.message}</p>}
      {message && <p className="registry-status" role="status">{message}</p>}
      {data && <>
        <p className="registry-caption">{data.scope === 'memory' ? '当前为内存测试运行，重启不保留。' : '已启用数据库保存；API 和 Worker 共用配置。'} 配置版本 {data.revision}</p>
        {tab === 'models' && <>
          <div className="registry-toolbar"><button className="registry-primary" disabled={busy || !data.connections.length} onClick={() => setEditor({ kind: 'models' })}><Plus size={16} /> 新增模型</button>
            {!data.connections.length && <button onClick={() => setEditor({ kind: 'connections' })}>先添加连接</button>}
            {!data.models.length && !data.connections.length && <button disabled={busy} onClick={() => void act(() => modelRegistry.import(data.revision), '已导入当前配置；未调用模型。')}>导入当前 API 配置</button>}
          </div>
          {!data.models.length && <div className="registry-empty"><h3>把常用模型保存在这里</h3><p>先添加连接和密钥，再添加该连接下的模型。已有配置也可以直接导入。</p></div>}
          <div className="registry-cards">{data.models.map(model => {
            const connection = data.connections.find(c => c.id === model.connectionId)
            const uses = Object.entries(data.bindings).filter(([, id]) => id === model.id).map(([key]) => data.usages[key])
            return <article className="registry-card" key={model.id} aria-label={model.name}>
              <div className="registry-card-content"><h3>{model.name} {!model.enabled && <span className="registry-badge">未启用</span>}</h3>
                <p>{data.templates[model.protocol]?.name} · {model.model}</p><small>{connection?.name} · {connection?.baseUrl}</small>
                <div className="registry-tags">{uses.map(use => <span key={use}>{use}</span>)}</div>
              </div>
              <div className="registry-card-actions">
                <button aria-label={`编辑 ${model.name}`} onClick={() => setEditor({ kind: 'models', value: model })}><Pencil size={16} /></button>
                <button aria-label={`复制 ${model.name}`} onClick={() => setEditor({ kind: 'models', value: model, copy: true })}><Copy size={16} /></button>
                <button disabled={busy} onClick={async () => {
                  setError(''); setBusy(true)
                  try { setPreview(await modelRegistry.preview(model.id)) }
                  catch (cause) { setError(cause instanceof Error ? cause.message : '预览失败') }
                  finally { setBusy(false) }
                }}>离线预览</button>
                <button aria-label={`删除 ${model.name}`} disabled={busy || uses.length > 0} title={uses.length ? '请先在用途选择中解除引用' : '删除模型'} onClick={() => setPendingDelete({ kind: 'models', id: model.id })}><Trash2 size={16} /></button>
              </div>
            </article>
          })}</div>
        </>}
        {tab === 'connections' && <>
          <div className="registry-toolbar"><button className="registry-primary" onClick={() => setEditor({ kind: 'connections' })}><Plus size={16} /> 新增连接</button></div>
          <p className="registry-caption">同一平台的多个模型可以复用一个连接；不同账户或不同密钥请分别建立连接。</p>
          {data.connections.map(connection => <article className="registry-card" key={connection.id} aria-label={connection.name}>
            <div className="registry-card-content"><h3>{connection.name}</h3><p>{connection.baseUrl}</p><small>{connection.configured ? '密钥已加密保存' : '尚未填写密钥'}</small>
              <ConnectionTest key={`${connection.id}-${data.revision}`} connection={connection} data={data} />
            </div>
            <div className="registry-card-actions"><button aria-label={`编辑连接 ${connection.name}`} onClick={() => setEditor({ kind: 'connections', value: connection })}><Pencil size={16} /></button>
              <button aria-label={`删除连接 ${connection.name}`} disabled={busy || data.models.some(m => m.connectionId === connection.id)} onClick={() => setPendingDelete({ kind: 'connections', id: connection.id })}><Trash2 size={16} /></button></div>
          </article>)}
        </>}
        {tab === 'bindings' && <div className="registry-bindings">
          <p>为每个用途选择已保存的模型。选择后立即保存，只影响下一次操作，正在执行的请求继续使用原配置。</p>
          {Object.entries(data.usages).map(([usage, label]) => <label key={usage}>{label}
            <select aria-label={label} disabled={busy} value={data.bindings[usage] ?? ''} onChange={event => {
              const id = event.target.value || null
              void act(() => modelRegistry.bind(data.revision, { ...data.bindings, [usage]: id }), `${label}已更新；未调用模型。`)
            }}><option value="">沿用服务器原配置</option>{data.models.filter(model => model.enabled && data.templates[model.protocol]?.usages.includes(usage) && data.connections.find(c => c.id === model.connectionId)?.configured).map(model => <option key={model.id} value={model.id}>{model.name} · {model.model}</option>)}</select>
          </label>)}
          <p className="registry-caption">图生图只列出支持编辑参考图的协议。H3 选择中文 Context-IR 时不调用本地视频提示词润色；原视频配音保持原流程。</p>
        </div>}
        {pendingDelete && <div className="registry-delete" role="alert"><span>确认删除这条配置？已有生成素材不会删除。</span><button disabled={busy} onClick={() => void act(() => modelRegistry.remove(pendingDelete.kind, pendingDelete.id, data.revision), '配置已删除。')}>确认删除</button><button onClick={() => setPendingDelete(null)}>取消</button></div>}
        {preview && <div className="registry-preview"><div className="registry-toolbar"><strong>离线预览 · 未发送请求</strong><button onClick={() => setPreview(null)}>收起</button></div><p>尖括号内容代表生成时填入的输入，本预览不会扩写提示词。</p><pre>{JSON.stringify(preview, null, 2)}</pre></div>}
        <footer className="registry-footer"><span>语音、口型与新私有协议仍按已有适配器支持范围。</span></footer>
        {editor && <RegistryEditor data={data} editor={editor} onClose={() => setEditor(null)} onSaved={async value => { await update(value); setEditor(null); setMessage('配置已保存。请在“用途选择”中指定使用位置；未调用模型。') }} />}
      </>}
    </section>
  </div>
}

function ConnectionTest({ connection, data }: { connection: ModelConnection; data: ModelCatalog }) {
  const models = data.models.filter(model => model.connectionId === connection.id && ['chat-completions', 'doubao-chat'].includes(model.protocol))
  const [modelId, setModelId] = useState(connection.configured ? models[0]?.id ?? '' : '')
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<ConnectionTestResult | null>(null)
  const [error, setError] = useState('')
  const run = async () => {
    if (running) return
    setRunning(true); setError(''); setResult(null)
    try { setResult(await modelRegistry.testConnection(connection.id, data.revision, modelId || null)) }
    catch (cause) { setError(cause instanceof Error ? cause.message : '测试失败') }
    finally { setRunning(false) }
  }
  return <div className="registry-connection-test" aria-label={`${connection.name}连接测试`}>
    <div className="registry-toolbar">
      <select aria-label={`${connection.name}测试方式`} disabled={running} value={modelId} onChange={event => { setModelId(event.target.value); setResult(null); setError('') }}>
        <option value="">仅检查地址可达（不验证 Key）</option>
        {models.map(model => <option key={model.id} value={model.id} disabled={!connection.configured}>文本：{model.name} · {model.model}</option>)}
      </select>
      <button disabled={running} onClick={() => void run()}>{running ? '测试中…' : '测试连接'}</button>
    </div>
    <p className="registry-caption">{modelId ? '发送一次极短文本请求，输出上限设为1，供应商可能计费；最多等待15秒，不自动重试。' : '仅请求基础地址，不携带 Key，不生成图片或视频；不能据此确认鉴权和生成能力。'}</p>
    {result && <div className={result.status === 'failed' ? 'registry-error' : 'registry-test-result'} role={result.status === 'failed' ? 'alert' : 'status'}>
      <strong>{result.status === 'ok' ? '文本测试通过' : result.status === 'partial' ? '地址可达 · 模型尚未验证' : '测试失败'}</strong>
      <p>{result.message}</p>
      <small>{result.model ? `模型 ${result.model} · ` : ''}{result.upstreamStatus !== undefined ? `HTTP ${result.upstreamStatus} · ` : ''}{result.parameter ? `参数 ${result.parameter} · ` : ''}{result.elapsedMs} ms · 配置版本 {result.revision}</small>
    </div>}
    {error && <p className="registry-error" role="alert">{error}</p>}
  </div>
}

function RegistryEditor({ data, editor, onClose, onSaved }: { data: ModelCatalog; editor: Editor; onClose: () => void; onSaved: (value: ModelCatalog) => Promise<void> }) {
  const [revision] = useState(data.revision)
  const model = editor.kind === 'models' ? editor.value : undefined
  const connection = editor.kind === 'connections' ? editor.value : undefined
  const isCopy = editor.kind === 'models' && editor.copy
  const [name, setName] = useState(`${editor.value?.name ?? ''}${isCopy ? ' 副本' : ''}`)
  const [baseUrl, setBaseUrl] = useState(connection?.baseUrl ?? '')
  const [apiKey, setApiKey] = useState('')
  const [connectionId, setConnectionId] = useState(model?.connectionId ?? data.connections[0]?.id ?? '')
  const [protocol, setProtocol] = useState(model?.protocol ?? 'chat-completions')
  const [modelId, setModelId] = useState(model?.model ?? '')
  const [enabled, setEnabled] = useState(model?.enabled ?? true)
  const [json, setJson] = useState(JSON.stringify(model?.config ?? data.templates['chat-completions']?.defaults ?? {}, null, 2))
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const changeProtocol = (value: string) => { setProtocol(value); setJson(JSON.stringify(data.templates[value].defaults, null, 2)); setError('') }
  let videoConfig: Record<string, unknown> | null = null
  try {
    const value: unknown = JSON.parse(json)
    if (value && typeof value === 'object' && !Array.isArray(value)) videoConfig = value as Record<string, unknown>
  } catch { /* Keep invalid JSON visible for correction instead of overwriting it. */ }
  const changeVideoConfig = (field: string, value: string) => {
    if (!videoConfig) { setError('请先修正调用参数 JSON，再选择分辨率或档位。'); return }
    setJson(JSON.stringify({ ...videoConfig, [field]: value }, null, 2)); setError('')
  }
  const save = async () => {
    setBusy(true); setError('')
    try {
      let payload: Record<string, unknown>
      if (editor.kind === 'connections') payload = { revision, name, baseUrl, ...(apiKey ? { apiKey } : {}) }
      else {
        let config: unknown
        try { config = JSON.parse(json) } catch { throw new Error('JSON 格式错误，请检查引号、逗号和括号。') }
        if (!config || typeof config !== 'object' || Array.isArray(config)) throw new Error('调用参数必须是 JSON 对象。')
        payload = { revision, name, connectionId, protocol, model: modelId, enabled, config }
      }
      const result = await modelRegistry.save(editor.kind, isCopy ? undefined : editor.value?.id, payload)
      setApiKey(''); await onSaved(result)
    } catch (cause) { setError(cause instanceof Error ? cause.message : '保存失败') }
    finally { setBusy(false) }
  }
  return <div className="registry-editor-backdrop"><section className="registry-editor" role="dialog" aria-modal="true" aria-label={editor.kind === 'models' ? '编辑模型' : '编辑连接'}>
    <header className="registry-toolbar"><h3>{editor.kind === 'models' ? '编辑模型' : '编辑连接'}</h3><button aria-label="关闭编辑" disabled={busy} onClick={onClose}><X size={18} /></button></header>
    <div className={editor.kind === 'models' ? 'registry-editor-grid' : ''}><fieldset disabled={busy}>
      <label>{editor.kind === 'models' ? '显示名称' : '连接名称'}<input value={name} onChange={e => setName(e.target.value)} /></label>
      {editor.kind === 'connections' ? <>
        <label>API 基础地址<input placeholder="https://ark.cn-beijing.volces.com/api/v3" value={baseUrl} onChange={e => setBaseUrl(e.target.value)} /></label>
        <label>API Key<input type="password" autoComplete="new-password" placeholder={connection?.configured ? '已保存，留空保留' : '仅发送到后端加密保存'} value={apiKey} onChange={e => setApiKey(e.target.value)} /></label>
        <p>模型复用此连接的地址和密钥。更换服务域名时需要重新填写对应密钥。</p>
      </> : <>
        <label>使用连接<select value={connectionId} onChange={e => setConnectionId(e.target.value)}>{data.connections.map(c => <option key={c.id} value={c.id}>{c.name}{c.configured ? '' : '（未配置密钥）'}</option>)}</select></label>
        <label>调用协议<select value={protocol} onChange={e => changeProtocol(e.target.value)}>{Object.entries(data.templates).map(([id, template]) => <option value={id} key={id}>{template.name}</option>)}</select></label>
        <label>API 模型 ID<input value={modelId} onChange={e => setModelId(e.target.value)} placeholder="填写供应商调用示例中的准确 model ID" /></label>
        <p>支持用途：{data.templates[protocol]?.usages.map(usage => data.usages[usage]).join('、')}</p>
        {protocol === 'xiangongyun-h3' && <p>选择已保存的仙宫云连接；地址为实例 web_url 根地址，密钥为 jupyter_token。模型 ID 填 MiniMax-H3，仅作记录。默认竖屏 544×960、平衡档，使用本地中文提示词，生成后保存到项目素材库。</p>}
        <label className="registry-check"><input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} />启用模型</label>
        <p>启用后还需在“用途选择”中指定。选择另一协议会重置右侧参数。</p>
      </>}
    </fieldset>
      {editor.kind === 'models' && <div className="registry-json">
        {protocol === 'xiangongyun-h3' && <>
          <label>仙宫云分辨率<select aria-label="仙宫云分辨率" disabled={busy || !videoConfig} value={String(videoConfig?.resolution ?? '')} onChange={e => changeVideoConfig('resolution', e.target.value)}>
            <option value="" disabled>请选择分辨率</option>
            {[
              ['0.4P', '480 × 832'], ['0.5P', '544 × 960'], ['0.6P', '576 × 1024'],
              ['0.7P', '640 × 1120'], ['0.8P', '672 × 1216'], ['0.9P', '704 × 1280'], ['1.0P', '768 × 1344'],
            ].map(([value, size]) => <option key={value} value={value}>{value} · 竖屏 {size}</option>)}
          </select></label>
          <label>仙宫云推理档位<select aria-label="仙宫云推理档位" disabled={busy || !videoConfig} value={String(videoConfig?.inferenceProfile ?? '')} onChange={e => changeVideoConfig('inferenceProfile', e.target.value)}>
            <option value="" disabled>请选择档位</option>
            <option value="turbo4_av_sol_gpu_te">极速</option><option value="turbo8_av_sol_gpu_te">平衡（默认）</option><option value="quality_av_sol_gpu_te">质量</option>
          </select></label>
          <p>横屏会交换宽高。选择后同步更新下方 JSON，保存模型后生效；已有任务保留原配置。</p>
        </>}
        <label htmlFor="registry-config-json">调用参数 JSON</label><textarea id="registry-config-json" aria-label="调用参数 JSON" spellCheck={false} disabled={busy} value={json} onChange={e => setJson(e.target.value)} />
        <div className="registry-toolbar"><button disabled={busy} onClick={() => setJson(JSON.stringify(data.templates[protocol].defaults, null, 2))}>填入协议默认参数</button>
          {['chat-completions', 'doubao-chat', 'chat-image'].includes(protocol) && <button disabled={busy} onClick={() => setJson(JSON.stringify({ ...data.templates[protocol].defaults, request: { path: '/chat/completions', body: { model: '{{model}}', messages: '{{messages}}', ...(protocol === 'chat-image' ? {} : { temperature: 0.7 }) } }, responseTextPath: 'choices[0].message.content' }, null, 2))}>填入请求模板</button>}
        </div><p>文本/Chat 图片支持 request.path、request.body、request.headers 和 responseTextPath。其他协议使用对应参数模板；H3 的参考图、时长和幂等规则由系统保持。</p>
      </div>}
    </div>
    {error && <p className="registry-error" role="alert">{error}</p>}
    <footer className="registry-toolbar"><button disabled={busy} onClick={onClose}>取消</button><button className="registry-primary" disabled={busy || !name.trim() || (editor.kind === 'models' ? !modelId.trim() || !connectionId : !baseUrl.trim())} onClick={() => void save()}>{busy ? '保存中…' : editor.kind === 'models' ? '保存模型' : '保存连接'}</button></footer>
  </section></div>
}
