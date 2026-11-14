import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { comicflowApi } from '../../api/client'
import type { VideoJob } from '../../types'
import { videoJobError, videoJobStages } from '../../video-jobs'
import { TechDetails } from '../../components/TechDetails'

export function VideoJobPanel({ job, candidate }: { job: VideoJob; candidate?: Record<string, unknown> }) {
  const [taskId, setTaskId] = useState('')
  const cache = useQueryClient()
  const recover = useMutation({
    mutationFn: () => comicflowApi.recoverVideo(job.projectId, job.id, job.canLinkTask ? taskId.trim() : undefined),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ['video-jobs', job.projectId] })
    },
  })
  const adopt = useMutation({
    mutationFn: () => comicflowApi.adoptVideo(job.projectId, job.id),
    onSettled: () => {
      void cache.invalidateQueries({ queryKey: ['video-jobs', job.projectId] })
      void cache.invalidateQueries({ queryKey: ['snapshot', job.projectId] })
      void cache.invalidateQueries({ queryKey: ['visual-preflight', job.projectId] })
      void cache.invalidateQueries({ queryKey: ['video-resources', job.projectId] })
      void cache.invalidateQueries({ queryKey: ['generation-session', job.projectId] })
    },
  })
  const error = videoJobError(job)
  return <section className="video-job-panel" aria-label="视频任务详情">
    <strong role="status">{videoJobStages[job.status] ?? job.status}</strong>
    {job.status === 'queued' && <p>任务已保存，等待后台开始处理；刷新页面不会重复提交。</p>}
    {error && <p role="alert">{error}</p>}
    {job.result && <p>{job.result.adopted ? '此结果已采用。' : '新视频已生成为候选，播放确认后再采用；当前视频会保留到采用成功。'}</p>}
    {candidate && <p className="video-job-note">采用后会替换本镜头视频，并需要重新合成成片；旧文件保留。</p>}
    {job.result && !job.result.adopted && job.status === 'succeeded' && <button
      disabled={adopt.isPending || !candidate || !candidate.downloadUrl}
      onClick={() => adopt.mutate()}
    >
      {adopt.isPending ? '正在采用…' : '采用此候选视频'}
    </button>}
    {adopt.error && <p role="alert">采用未成功：{adopt.error.message}。当前有效视频未改变，请刷新任务和准备单。</p>}
    {job.canRecover && <button disabled={recover.isPending} onClick={() => recover.mutate()}>
      {recover.isPending ? '正在安排恢复…' : job.taskId ? '继续查询 / 保存已有任务' : '继续处理已有作业'}
    </button>}
    {job.canLinkTask && <div className="video-job-link">
      <p>若供应商已创建任务，填写那一条任务号以继续查询。请确认属于当前镜头和原模型连接。</p>
      <label>已有供应商任务号<input value={taskId} onChange={e => setTaskId(e.target.value)} maxLength={128} /></label>
      <button disabled={recover.isPending || !/^[A-Za-z0-9_-]{1,128}$/.test(taskId.trim())} onClick={() => recover.mutate()}>关联并查询已有任务</button>
    </div>}
    {recover.error && <p role="alert">恢复未成功：{recover.error.message}。请刷新任务记录后核查。</p>}
    <TechDetails>
      <dl>
        <div><dt>作业编号</dt><dd>{job.id}</dd></div>
        <div><dt>供应商任务号</dt><dd>{job.taskId ?? '尚未记录'}</dd></div>
        <div><dt>提交模型</dt><dd>{job.model ?? '未知'} · 配置版本 {job.modelConfigRevision ?? '未知'}</dd></div>
        <div><dt>已开始的调用</dt><dd>文本 {job.callsStarted.text} 次 / 视频提交 {job.callsStarted.video} 次（不代表实际扣费）</dd></div>
        {job.errorDetail?.upstreamStatus != null && <div><dt>上游状态</dt><dd>上游 HTTP {String(job.errorDetail.upstreamStatus)}</dd></div>}
      </dl>
      {candidate && <p>采用会清除相关音频时间轴与成片，并使依赖旧尾帧的后续视频过期。</p>}
      <p>阶段记录：</p>
      <ol>{job.history.map((entry, index) =>
        <li key={`${entry.at}-${index}`}>{videoJobStages[entry.status] ?? entry.status} · {new Date(entry.at).toLocaleString()}</li>)}</ol>
    </TechDetails>
  </section>
}
