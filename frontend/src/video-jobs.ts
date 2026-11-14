import type { VideoJob } from './types'

export const videoJobStages: Record<string, string> = {
  queued: '已排队，等待执行器', preparing: '检查输入与参考图', expanding: '扩写镜头提示词',
  prepared: '提示词已保存，待提交', submitting: '正在提交供应商', polling: '查询已有供应商任务',
  downloading: '下载并保存视频', finalizing: '保存结果与首尾帧', rendering: '本地模拟生成',
  recoverable: '已中断，可恢复已有任务', unknown: '调用结果待核查，已阻止再次生成',
  succeeded: '已完成', failed: '已停止', cancelled: '已取消',
}

export function videoJobActive(job: VideoJob) {
  return !['succeeded', 'failed', 'cancelled'].includes(job.status)
}

export function videoJobError(job: VideoJob) {
  if (job.status === 'unknown') return '尚不能确认上游调用结果。请先核对供应商记录，不要重新生成。'
  if (job.error === 'VIDEO_JOB_CONFIG_CHANGED') return '原模型连接配置已变化，请恢复原配置后查询已有任务。'
  if (job.error === 'VIDEO_JOB_STORAGE_UNAVAILABLE') return '任务存储暂不可用，请先恢复数据库连接。'
  if (job.error === 'VIDEO_TASK_CANCELLED') return '供应商任务已取消。已有视频保留；新生成可能再次计费。'
  if (job.error === 'PROVIDER_TIMEOUT') return '等待模型服务超时。已保存任务号时，可继续查询或保存原任务；未自动重试。'
  if (job.error === 'VIDEO_RATE_LIMITED' || job.error === 'PROVIDER_RATE_LIMITED') return '供应商请求受限，请核对配额和频率限制；未自动重试。'
  if (job.error === 'PROVIDER_AUTH_FAILED') return '原模型连接鉴权失败，请核对对应连接的凭据；未自动重试。'
  if (job.error === 'PROVIDER_UNAVAILABLE') return '模型服务暂不可用。请先核查已有任务；未自动重试。'
  if (job.error) return `本次处理已停止（${job.error}）。已有结果保留，未自动重试。`
  return ''
}
