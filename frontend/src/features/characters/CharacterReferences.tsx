import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { apiErrorMessages, comicflowApi } from '../../api/client'
import type { CharacterCard, ImageJob, Snapshot } from '../../types'
import { createOperationId } from '../../operation-id'
import { TechDetails } from '../../components/TechDetails'

export function useCharacterReferenceActions(snapshot: Snapshot, card: CharacterCard | undefined, refresh: () => Promise<void>) {
  const projectId = snapshot.project.id
  const queryClient = useQueryClient()
  const queryKey = ['image-jobs', projectId]
  const jobs = useQuery({ queryKey, queryFn: () => comicflowApi.imageJobs(projectId), refetchInterval: 2000 })
  const history = (jobs.data?.items ?? []).filter(job => job.characterId === card?.id)
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt))
  const active = history.find(job => !['succeeded', 'failed', 'cancelled'].includes(job.status))
  const latest = active ?? history[0]
  const revision = history.map(job => `${job.id}:${job.updatedAt}`).join('|')
  const seen = useRef('')
  useEffect(() => {
    if (revision && revision !== seen.current) {
      seen.current = revision
      void refresh()
    }
  }, [revision, refresh])
  // Retain the logical operation after a lost HTTP response; never invent a new paid retry.
  const operations = useRef<Partial<Record<'candidate' | 'board' | 'text-board', string>>>({})
  const submit = async (purpose: 'candidate' | 'board' | 'text-board') => {
    const operationId = operations.current[purpose] ?? createOperationId()
    operations.current[purpose] = operationId
    const job = await comicflowApi.requestImageJob(projectId, card!.id, snapshot.project.version, purpose, operationId)
    delete operations.current[purpose]
    await queryClient.invalidateQueries({ queryKey })
    return job
  }
  const reference = useMutation({
    mutationFn: () => submit('candidate'),
    onSuccess: refresh,
  })
  const approve = useMutation({
    mutationFn: () => comicflowApi.approveCharacterReferenceCandidate(snapshot.project.id, card!.id, card!.referenceImageCandidate!.id, snapshot.project.version),
    onSuccess: refresh,
  })
  const viewGeneration = useMutation({
    mutationFn: () => submit('board'),
    onSuccess: refresh,
  })
  const textBoardGeneration = useMutation({
    mutationFn: () => submit('text-board'),
    onSuccess: refresh,
  })
  const approveBoard = useMutation({
    mutationFn: () => comicflowApi.approveCharacterReferenceBoard(projectId, card!.id, card!.referenceBoardCandidate!.id, snapshot.project.version),
    onSuccess: refresh,
  })
  const recover = useMutation({
    mutationFn: () => comicflowApi.recoverImageJob(projectId, latest!.id),
    onSuccess: async () => { await queryClient.invalidateQueries({ queryKey }); await refresh() },
  })
  return { reference, approve, viewGeneration, textBoardGeneration, approveBoard, latest, jobs, recover, history, active,
    styleName: snapshot.project.visualStyleProfile?.name,
    busy: Boolean(active) || jobs.isPending || jobs.isError || reference.isPending || approve.isPending || viewGeneration.isPending || textBoardGeneration.isPending || recover.isPending || approveBoard.isPending }
}

const jobLabels: Record<string, string> = {
  queued: '图片作业已排队', preparing: '正在准备图片', submitting: '正在提交图片生成',
  polling: '正在查询图片结果', finalizing: '正在保存图片', composing: '正在整理参考板',
  succeeded: '图片作业已完成', recoverable: '图片作业中断，可恢复已有进度',
  unknown: '提交结果未知：本地执行已停止，不会继续等待出图。',
  failed: '图片作业失败，已停止执行。', cancelled: '本地图片作业已关闭，未重新提交。',
}

function ImageJobDetails({ job }: { job: ImageJob }) {
  const purpose = job.purpose === 'text-board' ? '文字设定板' : job.purpose === 'board' ? '三视图整板' : job.purpose === 'views' ? '分视图' : '主图'
  return <article className="character-job-record">
    <strong>上次{purpose}作业</strong>
    <p><time dateTime={job.createdAt}>{new Date(job.createdAt).toLocaleString('zh-CN', { hour12: false })}</time> · {jobLabels[job.status] ?? job.status}</p>
    <p>已保存 {job.completedSteps.filter(step => step !== 'board').length} 张</p>
    <TechDetails>
      <p>提交尝试 {job.callsStarted} 次（不代表实际计费次数）</p>
      {job.taskId && <p>供应商任务号：{job.taskId}</p>}
    </TechDetails>
    {job.error && <details><summary>查看错误详情</summary>
      <p>{apiErrorMessages[job.error] ?? '请核对已有调用记录。'}</p>
      <p>本地作业号：{job.id}</p><p>错误代码：{job.error}</p>
      {job.errorDetail?.upstreamStatus && <p>上游 HTTP：{job.errorDetail.upstreamStatus}</p>}
      {job.errorDetail?.upstreamCode && <p>供应商错误码：{job.errorDetail.upstreamCode}</p>}
      {job.errorDetail?.requestId && <p>供应商请求号：{job.errorDetail.requestId}</p>}
      {job.errorDetail?.transportError && <p>网络异常类型：{job.errorDetail.transportError}</p>}
      {!job.errorDetail && <p>此旧记录没有保留上游错误详情。</p>}
    </details>}
    {job.applied === false && <p>角色来源已改变，结果已保留，未覆盖当前素材。</p>}
    {job.applied === false && job.assets?.map(asset => asset.url && <a key={asset.id} href={asset.url} target="_blank" rel="noreferrer">查看已保留图片（{asset.step}）</a>)}
  </article>
}

export function CharacterReferences({ card, actions, unsaved, busy }: {
  card?: CharacterCard
  actions: ReturnType<typeof useCharacterReferenceActions>
  unsaved: boolean
  busy: boolean
}) {
  const { reference, approve, viewGeneration, textBoardGeneration, approveBoard, latest, jobs, recover, history, active } = actions
  const [mode, setMode] = useState<'text-board' | 'board' | 'candidate'>('text-board')
  const hasReferenceImage = Boolean(card?.referenceImageUrl && card.referenceImageMediaType === 'image')
  const candidate = card?.referenceImageCandidate
  const boardCandidate = card?.referenceBoardCandidate
  const board = card?.referenceBoard
  const referenceViews = card?.referenceViews ?? []
  const generation = mode === 'text-board' ? textBoardGeneration : mode === 'board' ? viewGeneration : reference
  const showProgress = latest && (active || latest.status === 'failed' || latest.applied === false)
  const otherJobs = history.filter(job => !showProgress || job.id !== latest?.id)
  const modeDescription = mode === 'text-board'
    ? '按外观和服装重新定妆：脸部特写＋正面、侧面、背面全身，一次生成一张板。'
    : mode === 'board' ? '以已确认主图为参考生成三视图，保持人物身份。'
      : '按角色参考图提示词生成一张主图，确认后可用于图生图。'
  const confirmedBoard = board?.url && board.status !== 'stale' && <section aria-label="已确认角色参考板" className="character-image-result">
    <strong>已确认参考板</strong><p>用于视频的人物参考。</p>
    <img src={board.url} alt={`${card!.name}已确认参考板`} />
  </section>
  const mainCandidate = candidate && card && <section className="character-image-result is-candidate" aria-label="角色候选参考图">
    <strong>候选主图 · 待确认</strong><p>确认前不会用于视频。</p>
    <img src={candidate.url} alt={`${card.name}候选参考图`} />
    <button disabled={busy || unsaved || !candidate.id || candidate.status === 'stale'} onClick={() => approve.mutate()}>{approve.isPending ? '确认中…' : '确定使用这张图'}</button>
    {approve.error && <p role="alert">确认失败：{approve.error.message}</p>}
  </section>
  const mainImage = hasReferenceImage && card && <section aria-label="已确认角色主图" className="character-image-result">
    <strong>已确认主图</strong><img src={card.referenceImageUrl} alt={`${card.name}已确认参考图`} />
  </section>
  return <section className="character-images" aria-label="角色图片">
    <header><h3>角色参考图</h3><span>{boardCandidate || candidate ? '有候选待确认' : board?.status === 'stale' ? '参考板已失效' : board?.url ? '已确认设定板' : hasReferenceImage ? '已确认主图' : '尚未生成'}</span></header>
    <section aria-label="角色参考图生成" className="character-image-controls">
      <label>生成方式<select aria-label="图片生成方式" value={mode} disabled={busy} onChange={event => setMode(event.target.value as typeof mode)}>
        <option value="text-board">文字生成设定板（推荐）</option>
        <option value="board" disabled={!hasReferenceImage}>基于主图生成三视图{!hasReferenceImage ? '（需先确认主图）' : ''}</option>
        <option value="candidate">生成单张主图</option>
      </select></label>
      <button className="character-image-generate" disabled={!card || !card.appearance || !card.clothing || unsaved || busy || (mode === 'board' && !hasReferenceImage)} onClick={() => generation.mutate()}>{generation.isPending ? '提交中…' : '生成图片'}</button>
      <p className="character-image-hint">{modeDescription} 每次生成可能计费。</p>
      {unsaved && <p role="status">请先保存角色设定，再生成或确认图片。</p>}
      {generation.error && <p role="alert">图片生成失败：{generation.error.message}</p>}
      <details className="character-fold"><summary>输入与模型说明</summary>
        <p>{mode === 'text-board' ? '使用已保存外观、服装和项目画风，不传入已有主图，不使用主图提示词；不额外调用文本模型。使用模型 API 中“图片生成”的绑定。'
          : mode === 'board' ? '使用模型 API 中“参考图/三视图编辑”的绑定及尺寸，传入已确认主图。'
            : '使用模型 API 中“图片生成”的绑定；主图提示词留空时使用角色设定。'}</p>
        <p>{actions.styleName ? `项目画风：${actions.styleName}` : '此项目未设置统一画风；文字设定板如需指定画风，请在外观设定中明确并保存。'}</p>
        <p>重新生成仅保存候选，不会直接覆盖当前已确认素材。</p>
      </details>
    </section>
    {jobs.error && <p role="alert">图片作业读取失败，请刷新后核查，暂不提交新生成。</p>}
    {showProgress && <section aria-label="图片生成进度" className="character-image-progress">
      <p role="status">{jobLabels[latest.status] ?? latest.status}</p>
      {latest.status === 'unknown' && <p>请先核对供应商记录。为避免重复扣费，已暂停该角色的新图片生成；刷新或等待不会自动恢复。</p>}
      {latest.error && <p>{apiErrorMessages[latest.error] ?? '请查看作业详情。'}</p>}
      {latest.applied === false && <p>来源已改变，结果未覆盖当前素材，请展开查看。</p>}
      {latest.canRecover && <button disabled={recover.isPending} onClick={() => recover.mutate()}>恢复已有图片作业</button>}
      {recover.error && <p role="alert">恢复失败：{recover.error.message}</p>}
      <details className="character-fold"><summary>作业详情</summary><ImageJobDetails job={latest} /></details>
    </section>}
    {boardCandidate && card && <section className="character-image-result is-candidate" aria-label="候选角色参考板">
      <strong>候选设定板 · 待确认</strong>
      <p>{boardCandidate.status === 'stale' ? '来源已改变，此候选不可确认。' : boardCandidate.generationMode === 'single-text-board' ? '检查脸部特写与三视图的人物、服装是否一致，满意后确认。' : '检查正面、侧面和背面，满意后确认。'}</p>
      <img src={boardCandidate.url} alt={`${card.name}候选三视图整板`} />
      <button disabled={busy || unsaved || boardCandidate.status === 'stale'} onClick={() => approveBoard.mutate()}>{approveBoard.isPending ? '确认中…' : '确定使用这张参考板'}</button>
      {approveBoard.error && <p role="alert">参考板确认失败：{approveBoard.error.message}</p>}
    </section>}
    {boardCandidate && mainCandidate ? <details className="character-fold"><summary>查看候选主图</summary>{mainCandidate}</details> : mainCandidate}
    {confirmedBoard && (boardCandidate || candidate ? <details className="character-fold"><summary>查看当前已确认参考板</summary>{confirmedBoard}</details> : confirmedBoard)}
    {board?.status === 'stale' && <section aria-label="已失效角色参考板">
      <p role="status">旧参考板已失效，不会用于新视频。</p>
      {board.url && <details className="character-fold"><summary>查看旧参考板</summary>
        <img className="character-secondary-image" src={board.url} alt={`${card!.name}已失效参考板`} />
      </details>}
    </section>}
    {mainImage && (board?.url || boardCandidate || candidate ? <details className="character-fold"><summary>查看已确认主图</summary>{mainImage}</details> : mainImage)}
    {!boardCandidate && !candidate && !board?.url && !hasReferenceImage && <p className="character-image-empty">生成后在这里查看图片，满意再确认使用。</p>}
    {referenceViews.length > 0 && <details className="character-fold"><summary>历史分图素材（{referenceViews.length}）</summary>
      <div className="character-reference-views" aria-label="历史角色三视图">{referenceViews.map(view => <figure key={view.id}><img src={view.url} alt={`${card!.name}${view.viewLabel ?? view.view ?? ''}`} /><figcaption>{view.viewLabel ?? view.view}</figcaption></figure>)}</div>
    </details>}
    {otherJobs.length > 0 && <details className="character-fold"><summary>生成记录（{otherJobs.length}）</summary>
      <p>仅查看记录，不会自动生成。</p>
      {otherJobs.map(job => <ImageJobDetails key={job.id} job={job} />)}
    </details>}
  </section>
}
