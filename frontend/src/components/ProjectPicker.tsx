import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { comicflowApi } from '../api/client'
import { useWorkspace } from '../stores/workspace'
import type { Snapshot } from '../types'
import './project-picker.css'

export function projectTitle(snapshot: Snapshot): string {
  return snapshot.script?.title || snapshot.project.script?.title
    || snapshot.project.input?.story?.slice(0, 60) || '未命名项目'
}

export function ProjectPicker({ onClose }: { onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const searchField = useRef<HTMLInputElement>(null)
  const [search, setSearch] = useState('')
  const { projectId, openExistingProject } = useWorkspace()
  const projects = useQuery({
    queryKey: ['project-list'],
    queryFn: async () => {
      const result = await comicflowApi.listProjects()
      if (!Array.isArray(result)) throw new Error('PROJECT_LIST_INVALID')
      return result
    },
    retry: false,
    refetchOnWindowFocus: false,
  })
  useEffect(() => {
    const element = dialog.current!
    element.showModal()
    searchField.current?.focus()
    return () => element.close()
  }, [])
  const query = search.trim().toLocaleLowerCase()
  const matches = (projects.data ?? []).filter(item =>
    `${projectTitle(item)} ${item.project.id}`.toLocaleLowerCase().includes(query))
  function close() {
    dialog.current?.close()
    onClose()
  }
  function openProject(item: Snapshot) {
    if (item.project.id !== projectId) {
      openExistingProject(item.project.id, (item.script ?? item.project.script)?.shots.length ? 'script' : 'create')
    }
    close()
  }
  return <dialog ref={dialog} className="project-picker" aria-labelledby="project-picker-title"
    onCancel={event => { event.preventDefault(); close() }} onClick={event => { if (event.target === event.currentTarget) close() }}>
    <header>
      <div><h2 id="project-picker-title">打开已有项目</h2><p>打开项目不调用生成模型。</p></div>
      <button type="button" aria-label="关闭项目列表" onClick={close}>关闭</button>
    </header>
    {projectId && <p className="project-picker-note">切换前请先保存当前编辑。已提交的生成任务会继续执行，切换项目不会取消任务。</p>}
    <label>搜索项目<input ref={searchField} type="search" aria-label="搜索项目" placeholder="输入项目标题或编号"
      value={search} onChange={event => setSearch(event.target.value)} /></label>
    {projects.isPending ? <p role="status">正在读取项目…</p>
      : projects.isError ? <div role="alert">项目列表读取失败。<button type="button" disabled={projects.isFetching}
        onClick={() => { void projects.refetch() }}>重新读取</button></div>
      : !projects.data?.length ? <p>还没有可打开的项目。</p>
      : <><p role="status">找到 {matches.length} 个项目</p>
        {!matches.length && <p>没有匹配的项目，请换一个标题或编号。</p>}
        <ul>{matches.map(item => <li key={item.project.id}>
          <button type="button" aria-label={`打开 ${projectTitle(item)} ${item.project.id}`}
            aria-current={item.project.id === projectId ? 'true' : undefined} onClick={() => openProject(item)}>
            <strong>{projectTitle(item)}{item.project.id === projectId && <span> · 当前项目</span>}</strong>
            <small>{item.project.id} · {(item.script ?? item.project.script)?.shots.length ?? 0} 个镜头</small>
          </button>
        </li>)}</ul></>}
  </dialog>
}
