import { useMutation } from '@tanstack/react-query'
import { Check, Mail, X } from 'lucide-react'
import { useState } from 'react'
import { comicflowApi } from '../api/client'

export function ClaimProjectDialog({ projectId, onClose, onClaimed }: { projectId: string; onClose: () => void; onClaimed: (userId: string, credits: number) => void }) {
  const [email, setEmail] = useState('')
  const [token, setToken] = useState('')
  const [sent, setSent] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const send = useMutation({ mutationFn: () => comicflowApi.requestMagicLink(email), onSuccess: () => { setSent(true); setError(null) }, onError: (value: Error) => setError(value.message) })
  const verify = useMutation({ mutationFn: async () => { const session = await comicflowApi.verifyMagicLink(token); await comicflowApi.claimProject(projectId); const credits = await comicflowApi.projectCredits(projectId); return { session, credits } }, onSuccess: ({ session, credits }) => { localStorage.setItem('comicflow-user-id', session.userId); onClaimed(session.userId, credits.available) }, onError: (value: Error) => setError(value.message) })
  return <div className="modal-backdrop"><section className="model-dialog" role="dialog" aria-modal="true" aria-labelledby="claim-title"><div className="model-dialog-head"><div><Mail size={18} color="var(--accent)" /><h2 id="claim-title">登录并认领项目</h2><p>登录后可跨设备保存和下载导出包。</p></div><button className="icon-button" aria-label="关闭" onClick={onClose}><X size={16} /></button></div><label>邮箱<input aria-label="邮箱" type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="creator@example.com" /></label>{sent && <label>验证码<input aria-label="验证码" value={token} onChange={(event) => setToken(event.target.value)} placeholder="粘贴登录链接中的验证码" /></label>}{error && <div className="error-banner" role="alert">{error}</div>}<button className="primary-command" disabled={send.isPending || verify.isPending || !email.includes('@') || (sent && !token)} onClick={() => sent ? verify.mutate() : send.mutate()}>{sent ? <><Check size={16} />验证并认领</> : '发送登录链接'}</button></section></div>
}
