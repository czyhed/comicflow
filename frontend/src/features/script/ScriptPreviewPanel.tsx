import { Clapperboard, Mic } from 'lucide-react'
import { useEffect, useRef } from 'react'
import type { ScriptPreview } from '../../types'
import { speechBudget } from './script-budget'

const sceneFields = { time: '时间', location: '地点', narrativeGoal: '叙事目标', conflict: '冲突', turningPoint: '转折' } as const
const pad = (value: number) => String(value).padStart(2, '0')

export function ScriptPreviewPanel({ preview, pending, error, onCancel, onConfirm }: {
  preview: ScriptPreview
  pending: boolean
  error?: Error | null
  onCancel: () => void
  onConfirm: () => void
}) {
  const rootRef = useRef<HTMLElement>(null)
  const blocked = error?.message === 'VERSION_CONFLICT'
  const actionLabel = pending ? '正在写入…' : '确认并进入剧本编辑器'
  useEffect(() => {
    // The preview may be taller than the viewport; make sure its header (which
    // now carries a confirm button) is visible when the panel opens.
    rootRef.current?.scrollIntoView({ block: 'start', behavior: 'smooth' })
  }, [])
  const shots = new Map(preview.script.shots.map(shot => [shot.id, shot]))
  const totalSec = preview.script.shots.reduce((sum, shot) => sum + shot.durationSec, 0)
  const overBudget = preview.script.shots.filter(shot => speechBudget(shot).status === 'over').length
  return <section className="script-review" role="region" aria-label="剧本拆分预览" ref={rootRef}>
    <header>
      <div>
        <span className="review-kicker">拆分预览 · 尚未保存</span>
        <h2>{preview.script.title}</h2>
        <p>{preview.summary.scenes} 个场景 · {preview.summary.shots} 个镜头 · {preview.summary.dialogue} 条对白 · {preview.summary.narration} 条旁白 · {totalSec} 秒</p>
        {overBudget > 0 && <p className="review-warning">{overBudget} 个镜头台词偏长，进入编辑器后可以按提示删减。</p>}
      </div>
      <button className="script-preview-open script-preview-open-top" onClick={onConfirm} disabled={pending || blocked}>{actionLabel}</button>
    </header>
    <div className="script-review-content">
      {preview.script.scenes.map((scene, sceneIndex) => <section className="script-review-scene" key={scene.id}>
        <h3><span className="scene-index">场景 {pad(sceneIndex + 1)}</span>{scene.title}</h3>
        <dl>{(['time', 'location', 'narrativeGoal', 'conflict', 'turningPoint'] as const).map(field => <div key={field}>
          <dt>{sceneFields[field]}</dt><dd className={scene[field] ? '' : 'empty'}>{scene[field] || '未提供'}</dd>
        </div>)}</dl>
        {scene.shotIds.map(id => {
          const shot = shots.get(id)
          if (!shot) return null
          const budget = speechBudget(shot)
          return <article className="script-review-shot" key={id}>
            <h4><span className="shot-index">{pad(shot.order)}</span>{shot.title}
              <small>{shot.durationSec} 秒 · {shot.shotSize}</small>
              {budget.status === 'over' && <em className="speech-badge over">台词 {budget.used}/{budget.limit}</em>}
            </h4>
            <div className="review-shot-body">
              <div>
                <h5><Clapperboard size={13} aria-hidden="true" />画面</h5>
                <p>画面：{shot.visualDescription}</p><p>动作：{shot.action} · 情绪：{shot.emotion}</p>
              </div>
              <div>
                <h5><Mic size={13} aria-hidden="true" />声音</h5>
                <p>对白：{shot.dialogue || '无'}</p><p>旁白：{shot.narration || '无'}</p>
              </div>
            </div>
          </article>
        })}
      </section>)}
    </div>
    {error && <div className="error-banner" role="alert">{error.message === 'VERSION_CONFLICT'
      ? '项目已被修改，本预览未保存。请返回后重新生成预览，旧剧本未被覆盖。'
      : `保存失败，预览已保留：${error.message}`}</div>}
    <footer className="script-preview-footer">
      <button onClick={onCancel} disabled={pending}>返回修改内容</button>
      <button className="script-preview-open" onClick={onConfirm} disabled={pending || blocked}>{actionLabel}</button>
    </footer>
  </section>
}
