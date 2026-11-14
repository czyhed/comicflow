import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, UserPlus } from 'lucide-react'
import { useState } from 'react'
import { comicflowApi } from '../../api/client'
import type { Snapshot } from '../../types'
import { EmptyWorkspace } from '../script/ScriptWorkspace'
import { CharacterEditor } from './CharacterEditor'

export function CharacterWorkspace({ snapshot }: { snapshot?: Snapshot }) {
  if (!snapshot?.script) return <EmptyWorkspace title="请先保存剧本，再管理角色" />
  return <ProjectCharacters key={snapshot.project.id} snapshot={snapshot} />
}

function ProjectCharacters({ snapshot }: { snapshot: Snapshot }) {
  const projectId = snapshot.project.id
  const queryClient = useQueryClient()
  const [selectedId, setSelectedId] = useState<string>()
  const cards = useQuery({ queryKey: ['characters', projectId], queryFn: () => comicflowApi.projectCharacters(projectId) })
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['characters', projectId] }),
      queryClient.invalidateQueries({ queryKey: ['snapshot', projectId] }),
    ])
  }
  const sync = useMutation({
    mutationFn: () => comicflowApi.syncProjectCharacters(projectId, snapshot.project.version),
    onSuccess: refresh,
  })
  const selected = selectedId === 'new' ? undefined : cards.data?.find((card) => card.id === selectedId) ?? cards.data?.[0]
  return <div className="character-layout">
    <aside className="character-list">
      <div className="column-title"><strong>项目角色</strong><button title="创建角色" onClick={() => setSelectedId('new')}><UserPlus size={15} /></button></div>
      <button onClick={() => sync.mutate()} disabled={sync.isPending}><RefreshCw size={15} />{sync.isPending ? '同步中…' : '从已保存剧本同步角色'}</button>
      <p className="list-hint">从剧本中读取角色名称，不消耗额度。</p>
      {cards.isPending && <p>正在读取角色…</p>}
      {cards.error && <p role="alert">角色读取失败：{cards.error.message}</p>}
      {sync.error && <p role="alert">同步失败：{sync.error.message}。请刷新后重试。</p>}
      {cards.data?.map((card) => <button className={selected?.id === card.id ? 'selected' : ''} key={card.id} onClick={() => setSelectedId(card.id)}>
        <span><strong>{card.name}</strong><small>{snapshot.script?.shots.filter((shot) => shot.characterIds?.includes(card.id)).length ?? 0} 个镜头</small></span>
      </button>)}
      {cards.data?.length === 0 && <p>还没有角色卡。若旧剧本未保存角色名称，请手动创建并绑定镜头。</p>}
    </aside>
    {selected || selectedId === 'new' ? <CharacterEditor key={selected?.id ?? 'new'} card={selected} snapshot={snapshot} onSaved={async (card) => { setSelectedId(card.id); await refresh() }} refresh={refresh} /> : <section className="character-stage"><p>保存剧本预览后会自动创建角色卡。旧项目可点击左侧同步按钮。</p></section>}
  </div>
}
