import { useQuery } from '@tanstack/react-query'
import { Check, Palette, Sparkles } from 'lucide-react'
import { request } from '../../api/client'
import type { VisualStyleProfile } from '../../types'

export function StylePresetPicker({ value, onChange, disabled, saved, hasProject }: {
  value: string; onChange: (id: string) => void; disabled: boolean
  saved?: VisualStyleProfile | null; hasProject: boolean
}) {
  const catalog = useQuery({
    queryKey: ['visual-styles'],
    queryFn: async () => {
      const result = await request<{ items: VisualStyleProfile[] }>('/api/visual-styles')
      if (!Array.isArray(result.items)) throw new Error('STYLE_CATALOG_INVALID')
      return result.items
    },
    staleTime: 300_000, retry: false, refetchOnWindowFocus: false,
  })
  const selected = catalog.data?.find(item => item.presetId === value)
  return <section className="style-library" aria-label="项目风格库">
    <div className="style-library-heading"><strong><Palette size={16} aria-hidden="true" />新项目画风</strong><span><Sparkles size={12} aria-hidden="true" />选择免费</span></div>
    <p className="style-library-hint">人物、场景与视频保持统一。仅应用于下次新建。</p>
    {hasProject && <p className="style-saved" role="status">{saved
      ? `当前项目画风：${saved.name} · v${saved.revision}`
      : '当前项目未统一设置画风，保留原有提示词。'}</p>}
    <label className="style-select-label">选择新项目画风
      <select aria-label="选择新项目画风" value={value} disabled={disabled}
        onChange={event => onChange(event.target.value)}>
        <option value="">未统一设置</option>
        {catalog.data?.map(item => <option key={item.presetId} value={item.presetId}>{item.name}</option>)}
      </select>
    </label>
    <div className="style-selection-preview" data-medium={selected?.medium ?? 'unset'}>
      <div className="style-color-study" aria-hidden="true"><i /><i /><i /></div>
      <div><span className="style-selection-label">{selected ? <><Check size={12} aria-hidden="true" />已选画风 · 色彩示意</> : '保留原有画风'}</span>
        <p>{selected?.description ?? '沿用各阶段已有提示词'}</p></div>
    </div>
      {catalog.isPending && <p role="status">正在读取风格库…</p>}
      {catalog.error && <div className="style-catalog-error"><p role="alert">风格库读取失败，可重试或保持未统一设置。</p>
        <button type="button" disabled={catalog.isFetching} onClick={() => void catalog.refetch()}>重新读取风格库</button>
      </div>}
    {selected && <details className="style-rule-summary" aria-label="所选画风规则">
      <summary>查看所选画风规则</summary>
      <strong>{selected.name} · 将用于新项目</strong>
      <dl className="style-rule-list">
        <div><dt>画面</dt><dd>{selected.rendering}</dd></div>
        <div><dt>光线</dt><dd>{selected.lighting}</dd></div>
        <div><dt>动态</dt><dd>{selected.motion}</dd></div>
        <div><dt>避免</dt><dd>{selected.avoid}</dd></div>
      </dl>
      <small>具体效果取决于所选模型和参考素材，角色设定图采用便于辨认的中性布光。</small>
    </details>}
  </section>
}
