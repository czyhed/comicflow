import { useEffect, useState } from 'react'
import type { TextProgress } from '../../api/textStream'

export function useTextGenerationProgress() {
  const [progress, setProgress] = useState({ text: '', phase: 'waiting', label: '' })
  return {
    ...progress,
    reset: () => setProgress({ text: '', phase: 'waiting', label: '' }),
    receive: (event: TextProgress) => setProgress(current => event.type === 'delta'
      ? { text: current.text + event.delta, phase: 'writing', label: current.label }
      : { ...current, phase: event.phase, label: event.label || '' }),
  }
}

function readableText(text: string, kind: 'story' | 'script'): string {
  if (!text.trimStart().startsWith('{') && !text.trimStart().startsWith('```')) return text
  const values = Array.from(text.matchAll(/"(text|title|visualDescription|dialogue|narration)"\s*:\s*"((?:[^"\\]|\\.)*)(?:"|$)/g))
  const decode = (raw: string) => {
    try { return JSON.parse(`"${raw}"`) as string } catch { return raw.replace(/\\n/g, '\n').replace(/\\"/g, '"') }
  }
  if (kind === 'story') return values.map(([, , value]) => decode(value)).join('\n\n').trim()
  return values.map(([, field, value]) => `${field}: ${decode(value)}`).join('\n').trim()
}

const phaseLabels: Record<string, string> = {
  'waiting': '请求已发出，等待模型返回...',
  'buffered': '当前接口整段返回，正在等待内容...',
  'writing': '正在生成内容...',
  'validating': '内容已返回，正在校验格式...',
  'quality-check': '✓ 检查故事质量',
  'generating-script': '⏳ 正在生成剧本（这可能需要 20-40 秒）',
  'continuity': '⏳ 应用延续性规则',
  'binding-characters': '⏳ 绑定角色信息',
}

export function TextGenerationProgress({ text, phase, label, kind }: { text: string; phase: string; label?: string; kind: 'story' | 'script' }) {
  const [seconds, setSeconds] = useState(0)
  useEffect(() => {
    const start = Date.now()
    const timer = window.setInterval(() => setSeconds(Math.floor((Date.now() - start) / 1000)), 1000)
    return () => window.clearInterval(timer)
  }, [])

  const isScriptGeneration = kind === 'script'
  const content = readableText(text, kind)
  const displayLabel = label || phaseLabels[phase] || phaseLabels['waiting']

  return <section className="text-generation-progress" aria-label="生成进展">
    <div role="status" aria-live="polite">
      <strong>{displayLabel}</strong>
      <span>已等待 {seconds} 秒</span>
    </div>
    {content && <pre className="generation-stream-preview" aria-label="实时生成内容">{content}</pre>}
    {isScriptGeneration && phase === 'generating-script' && (
      <small>剧本生成需要调用 AI 模型分析场景、镜头、对白等，请耐心等待。</small>
    )}
    {!isScriptGeneration && <small>内容正在生成，完整返回并校验后才能编辑或确认。</small>}
  </section>
}
