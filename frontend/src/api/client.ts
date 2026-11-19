import { readTextStream, type TextProgress } from './textStream'
import { createAudioApi } from './audio'
import { createCompositionApi } from './composition'
import { createStoryScriptApi } from './storyScripts'
import { createCharacterApi } from './characters'
import { createVideoApi } from './video'
import type { GenerationSession, Project, ReferenceImageAsset, Snapshot, WorkflowMode } from '../types'
import { preflightErrors } from '../visual-preflight'

export interface TextProviderConfigView {
  provider?: string
  baseUrl?: string
  model?: string
  timeoutMs?: number
  enabled: boolean
  configured: boolean
  apiKeyMasked: string
}

export interface ProviderRuntimeStatus {
  text: string
  visual: string
  tts: string
  lipSync: string
  composition: string
  image?: string
  imageAdapter?: string
  imageModel?: string
  imageProtocol?: string
  h3Prompt?: string
}

export interface MediaProviderConfigView extends TextProviderConfigView {
  imageProtocol?: string
  requestPath?: string
  statusPath?: string
  size?: string
  submitPath?: string
  queryPath?: string
  resolution?: string
  generationType?: string
  h3PromptMode?: string
  inferenceProfile?: string
}

export type ProviderCapability = 'text' | 'image' | 'video'
export type ProviderSlot = 'test' | 'production'
export interface ProviderProfilesView {
  active: ProviderSlot
  test: MediaProviderConfigView
  production: MediaProviderConfigView
}

export const apiErrorMessages: Record<string, string> = {
  ...preflightErrors,
  MODEL_CONFIG_CONFLICT: '配置已被另一窗口修改，请刷新后重新编辑。未覆盖已有配置。',
  MODEL_CONFIG_INVALID: '配置或 JSON 参数不符合所选协议，请检查字段、类型和模板变量。',
  MODEL_ENDPOINT_MISMATCH: '万相图片/视频使用原生 API 地址 /api/v1，不能使用文本兼容地址 /compatible-mode/v1。请为图片或视频创建独立连接并重新绑定模型。未调用模型。',
  MODEL_CONFIG_NOT_FOUND: '这条连接或模型已不存在，请刷新列表。',
  MODEL_CONFIG_IN_USE: '仍有模型或用途正在引用此配置，请先解除引用再删除。',
  MODEL_CONFIG_KEY_INVALID: '服务端模型配置加密密钥缺失或不匹配，请恢复原密钥文件。',
  MODEL_CONFIG_STORAGE_UNAVAILABLE: '模型库数据库尚未就绪。请检查数据库连接，并先执行 uv run alembic upgrade head。',
  MODEL_CAPABILITY_UNSUPPORTED: '该模型协议不支持所选用途，请选择具有相应能力的模型。',
  MODEL_REGISTRY_MANAGED: '当前用途已由模型库管理，请返回模型管理修改。',
  MODEL_CONFIG_IMPORT_REQUIRES_EMPTY: '模型库已有内容，不能重复导入并覆盖。',
  VIDEO_AUDIO_MISSING: '该视频没有可提取的原声音轨，未调用付费配音。请检查原视频声音。',
  VIDEO_AUDIO_UNREADABLE: '原视频文件读取失败，无法提取原声；未调用配音模型。',
  VIDEO_AUDIO_INVALID: '原视频的音轨无法解码，未调用配音模型。',
  VIDEO_AUDIO_STORE_FAILED: '原声已提取但保存失败，请检查对象存储。未调用配音模型。',
  FFMPEG_NOT_AVAILABLE: '服务器缺少 FFmpeg 或 ffprobe，无法处理已有媒体。',
  IMAGE_MODEL_UNSUPPORTED: '图片模型与所选接口协议不匹配。请在图片 API 配置中选择对应协议；wan2.6-image 使用万相 2.6 图文协议，自定义模型名称需手动指定兼容协议。不会自动替换模型。',
  IMAGE_REQUEST_INVALID: '图片服务拒绝了请求，请核对图片模型、接口地址、尺寸及提示词要求。未自动重试。',
  IMAGE_RATE_LIMITED: '图片服务请求频率受限，请稍后再操作。未自动重试。',
  IMAGE_QUOTA_EXHAUSTED: '图片服务报告额度或余额不足，请在百炼控制台核对当前模型额度。未自动切换或重试。',
  IMAGE_CONTENT_REJECTED: '图片服务的内容审核未通过，请调整角色设定或图片提示词。',
  IMAGE_DOWNLOAD_FAILED: '图片已生成，但结果下载失败；请先排查下载链路，避免重复生成扣费。',
  REFERENCE_BOARD_SIZE_INVALID: '请在模型控制台的图片编辑模型中配置正方形或横版尺寸，宽高比1至2.5，单边256至5760；不会自动提高分辨率。',
  REFERENCE_BOARD_STALE: '参考板来源已改变，请基于当前确认主图生成新板。',
  IMAGE_EDIT_UNSUPPORTED: '当前图片 Provider 不支持图生图。三视图需要 wan2.6-image 图像编辑协议。',
  IMAGE_EDIT_SOURCE_UNREADABLE: '已确认的角色参考图无法读取，未开始三视图生成。',
  IMAGE_EDIT_SOURCE_INVALID: '已确认的角色参考图格式无效，未开始三视图生成。',
  PROVIDER_AUTH_FAILED: '模型服务鉴权或权限校验失败，请核对当前配置的 API Key、地域和模型权限。',
  PROVIDER_REQUEST_INVALID: '模型服务拒绝请求，请核对供应商要求的模型 ID、API 地址和参数。',
  MODEL_CONNECTION_TEST_BUSY: '该连接正在测试，请等待结果，不要重复点击。',
  PROVIDER_RATE_LIMITED: '模型服务请求受限，请核对供应商配额与频率限制。',
  PROVIDER_UNAVAILABLE: '模型服务请求失败或暂时不可用。未自动重试，请核对配置及服务状态。',
  PROVIDER_TIMEOUT: '模型请求超时，尚不能确认是否已经生成；请先核对供应商任务记录，避免重复扣费。',
  PROVIDER_CREDENTIALS_REQUIRED: '更换供应商或服务域名时请填写对应的密钥，原密钥不会跨平台复用。',
  PROVIDER_NOT_CONFIGURED: '这套配置尚未保存有效密钥，请先配置再启用。',
  VIDEO_FIRST_FRAME_REQUIRED: '万相图生视频需要首帧图。请先准备镜头图片或单角色参考图，再生成视频。',
  VIDEO_FIRST_FRAME_UNREACHABLE: '首帧地址是本机或内网地址，云端模型无法访问。系统需要使用对象存储内容或公网地址，未提交视频请求。',
  VIDEO_FIRST_FRAME_UNREADABLE: '首帧已保存但服务端读取失败，未提交视频请求。',
  VIDEO_MODE_UNSUPPORTED: '当前视频模型不支持所选输入模式。万相基础图生视频只支持一张首帧，不支持 H3 多参考或首尾帧模式。',
  VIDEO_DURATION_INVALID: '镜头时长不符合当前模型限制。wan2.2-i2v-flash 固定 5 秒；wanx2.1-i2v-turbo 支持 3、4、5 秒。请在剧本中修改时长。',
  VIDEO_RESOLUTION_INVALID: '所选分辨率不适用于该视频模型，请修改视频配置。',
  VIDEO_REQUEST_INVALID: '视频平台拒绝了请求参数，请核对模型、接口协议、分辨率和镜头时长；具体错误码见后端日志。',
  VIDEO_QUOTA_EXHAUSTED: '视频平台额度不足，或已触发免费额度用完即停。请检查平台额度和计费设置。',
  VIDEO_RATE_LIMITED: '视频平台请求过于频繁，请稍后再手动尝试。',
  VIDEO_CONTENT_REJECTED: '视频平台未通过内容审核，请检查首帧图片和镜头描述。',
  CASCADE_FRAME_MISSING: '上一镜头没有可用尾帧；请先生成当前镜头的首帧，或为镜头绑定角色参考图。',
  VIDEO_PROMPT_TOO_LONG: '镜头描述超过当前模型的提示词长度限制，请精简后再生成。',
  VIDEO_PROMPT_REQUIRED: '请先填写镜头画面描述和动作。',
  CHARACTER_PROMPT_PROVIDER_REQUIRED: '请先在模型 API 管理中配置并启用文本 API，再生成角色提示词。',
  CHARACTER_PROMPT_INVALID: '模型未返回合格的中文角色提示词，已保留原设定，未自动重试。',
  CHARACTER_VERSION_CONFLICT: '角色已被其他操作修改，请刷新角色后核对再保存。',
  H3_PROMPT_WRITER_REQUIRED: '请在模型 API 管理中启用真实文本模型，供 H3 Skill 扩写使用。',
  H3_SKILL_UNAVAILABLE: '服务端缺少 H3 Skill 文件，请检查部署。未调用视频生成。',
  H3_REFERENCE_UNREADABLE: 'H3 参考图在服务端读取失败，尚未调用文本扩写或视频接口。请检查已保存的参考图。',
  H3_REFERENCE_UNREACHABLE: 'H3 参考图只有本机地址且没有可读取的存储对象，尚未调用文本或视频接口。请先保存可用参考图。',
  H3_REFERENCE_TOO_LARGE: 'H3 参考图总大小超出请求限制，尚未调用文本或视频接口。请减少参考图数量或大小。',
  H3_PROMPT_INVALID: 'Skill 扩写未通过校验，未提交 H3 视频生成。',
  H3_REFERENCE_MODE_CONFLICT: '首尾帧与参考图模式冲突，请选择一种输入方式。',
  H3_DURATION_INVALID: 'H3 镜头时长必须是 4–15 秒的整数。',
  REFERENCE_IMAGE_PROVIDER_REQUIRED: '请先在模型 API 管理中配置并启用图片 API。',
  REFERENCE_CANDIDATE_NOT_FOUND: '候选参考图不存在或已被替换，请重新生成。',
  REFERENCE_CANDIDATE_REQUIRED: '请先生成并确认角色候选参考图。',
  REFERENCE_CANDIDATE_VERSION_CONFLICT: '角色设定已经变化，请重新生成候选参考图。',
  REFERENCE_IMAGE_NOT_APPROVED: '请先确认角色参考图，再生成三视图。',
    REFERENCE_VIEWS_PARTIAL: '部分视角已生成，请检查已保存视角后重试缺失视角。',
    IMAGE_JOB_ACTIVE: '这个角色已有未结束的图片作业，请先查看或恢复原作业。',
    IMAGE_JOB_BUSY: '图片作业仍在执行，请等待页面更新。',
    IMAGE_SUBMISSION_UNKNOWN: '图片提交结果未知，请先核对供应商记录，勿重复生成。',
    IMAGE_JOB_STORAGE_UNAVAILABLE: '图片作业记录不可用，请检查数据库连接及图片作业迁移是否已应用。',
    IMAGE_JOB_NOT_RECOVERABLE: '该图片作业不能恢复，请刷新查看最新状态。',
  REFERENCE_IMAGE_INVALID: '参考素材不是有效图片，请重新准备参考图。',
}

const API_ROOT = import.meta.env.VITE_API_ROOT ?? ''

/** An API refusal that keeps the server's structured detail for the UI. */
export class ApiError extends Error {
  readonly status: number
  readonly detail: Record<string, unknown>

  constructor(code: string, status: number, detail: Record<string, unknown>) {
    super(code)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }

  /** Shot ids still missing a visual, when the server reported them. */
  get missingVisualShotIds(): string[] {
    const value = this.detail.missingVisualShotIds
    return Array.isArray(value) ? value.map(String) : []
  }

  /** Shot ids with a spoken line but no voice, when the server reported them. */
  get missingAudioShotIds(): string[] {
    const value = this.detail.missingAudioShotIds
    return Array.isArray(value) ? value.map(String) : []
  }
}

export async function request<T>(path: string, init?: RequestInit, onProgress?: (event: TextProgress) => void): Promise<T> {
  // Identity is injected by the ShiploadAI gateway (X-Control-User-Id). The
  // browser never supplies it, so no guest id is read from localStorage here.
  let response = await fetch(`${API_ROOT}${path}`, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...(onProgress ? { Accept: 'text/event-stream' } : {}),
      ...init?.headers,
    },
  })
  if (response.ok && onProgress && response.headers.get('content-type')?.includes('text/event-stream')) {
    response = await readTextStream(response, onProgress)
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { error?: string } & Record<string, unknown>
    const { error, ...detail } = body
    if (error === 'VIDEO_JOB_AWAITING_ADOPTION') throw new Error('请先在画面页播放并采用候选视频，再继续生成会话。')
    if (detail.stage === 'tts' && error === 'PROVIDER_AUTH_FAILED') {
      throw new ApiError('配音服务鉴权失败，请核对服务器上的百炼语音 Key。已有视频已保留，未自动重试。',
        response.status, detail)
    }
    // A text Adapter refusal carries the stage that issued the request. The H3
    // prompt is written before any video is submitted, so it must not read as a
    // failed video generation.
    const textStages: Record<string, { label: string; tail: string }> = {
      story_text: { label: '故事生成失败', tail: '未自动重试。' },
      script_split: { label: '剧本拆分失败', tail: '未自动重试。' },
      character_prompt: { label: '人物提示词生成失败', tail: '未保存提示词，未调用图片或视频模型，未自动重试。' },
      h3_text: { label: '镜头提示词扩写失败', tail: '尚未提交 H3 视频生成，未自动重试。' },
      text_check: { label: '文本配置连通性检查失败', tail: '本次为极短文本测试，可能计费；未自动重试。' },
    }
    const textStage = typeof detail.stage === 'string' ? textStages[detail.stage] : undefined
    if (detail.stage === 'script_split' && error === 'PROVIDER_INVALID_RESPONSE') {
      const reasons: Record<string, string> = {
        message_missing: '供应商响应中缺少模型消息',
        output_truncated: '模型输出因长度限制被截断，未返回完整剧本',
        reasoning_only: '模型只返回了思考内容，没有正式剧本',
        empty_content: '模型返回的正文为空',
        content_not_text: '模型正文不是可解析的文本',
        content_refused: '供应商拒绝返回本次内容',
        invalid_json: '模型正文不是完整可解析的 JSON 对象',
        invalid_envelope: '供应商 HTTP 响应不是可解析的 JSON',
        script_contract_invalid: '已解析 JSON，但剧本字段、镜头数量或场景引用未通过校验',
      }
      let explanation = reasons[String(detail.reason)] ?? '返回内容未通过校验'
      if (detail.reason === 'script_contract_invalid' && detail.validation
        && typeof detail.validation === 'object' && !Array.isArray(detail.validation)) {
        const validation = detail.validation as Record<string, unknown>
        const rules: Record<string, string> = {
          title_length: '剧本标题长度须为2–80字',
          array_required: '必须是数组', object_required: '必须是对象',
          required_text: '缺少必填文本或文本为空、长度不符', text_type: '必须是文本字符串',
          positive_duration: '镜头时长必须是正数，不能附带单位',
          total_duration: '镜头总时长必须在30–90秒内',
          speech_required: '该镜头的对白和旁白均为空',
          duplicate_id: '编号重复', string_list: '必须是字符串数组',
          nonempty_list: '镜头引用列表不能为空',
          generation_mode: '视频生成模式不在支持的范围内',
          scene_reference: '镜头所属场景与场景引用不一致',
          shot_references: '镜头引用存在遗漏、重复或不存在的镜头',
          routing: '返回的任务标识与剧本拆分不一致',
          shot_count: '镜头数量不符合本次要求', scene_count: '场景数量不符合本次要求',
        }
        const rule = String(validation.rule)
        if (rules[rule]) {
          const fieldPath = typeof validation.path === 'string' &&
            /^(envelope|title|shots|scenes)(\[\d{1,4}\])?(\.(id|title|action|emotion|shotSize|durationSec|visualDescription|dialogue|narration|sceneId|characters|characterIds|cameraMovement|visualStyle|soundscape|music|generationMode|shotIds|time|location|narrativeGoal|conflict|turningPoint))?$/.test(validation.path)
            ? `${validation.path}：` : ''
          explanation = fieldPath + rules[rule]
          const { actual, min, max } = validation
          if ((rule === 'shot_count' || rule === 'scene_count') &&
            [actual, min, max].every(value => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 && value <= 10000)) {
            explanation += `（实际${actual}个，要求${min === max ? min : `${min}–${max}`}个）`
          }
        }
      }
      throw new ApiError(
        `剧本拆分失败：${explanation}。` +
        '故事已保留，本次未保存拆分结果，未自动重试；本次文本请求可能已计费。',
        response.status, detail,
      )
    }
    if (detail.stage === 'character_prompt' && detail.reason === 'timeout') {
      const budget = typeof detail.timeoutMs === 'number' ? `（当前等待上限 ${detail.timeoutMs / 1000} 秒）` : ''
      throw new ApiError(
        `人物提示词生成失败：等待文本服务超时${budget}。未保存提示词，未调用图片或视频模型，未自动重试。` +
        '请在“模型 API → 用途选择 → 人物提示词”核对模型与 timeoutMs（最多300000毫秒）。' +
        '本次文本请求可能已计费，请先核对供应商调用记录。', response.status, detail,
      )
    }
    if (detail.stage === 'script_split' && detail.reason === 'timeout') {
      const phase = detail.timeoutPhase === 'connect' ? '连接文本服务超时'
        : detail.timeoutPhase === 'read' ? '等待文本模型响应超时' : '文本模型请求超时'
      const budget = typeof detail.timeoutMs === 'number' ? `（当前等待上限 ${detail.timeoutMs / 1000} 秒）` : ''
      throw new ApiError(
        `剧本拆分失败：${phase}${budget}。本次未保存拆分结果，未自动重试。` +
        '请在“模型 API → 用途选择 → 剧本拆分”找到对应模型，核对调用参数 JSON 中的 timeoutMs（最多300000毫秒）。' +
        '本次文本请求可能已计费；同步拆分没有可恢复的任务号，请查看供应商调用记录，勿连续重试。',
        response.status, detail,
      )
    }
    if (textStage && detail.reason === 'connection_error') {
      throw new ApiError(
        `${textStage.label}：无法连接文本服务或连接中断。${textStage.tail}请核对已有调用记录，勿连续重试。`,
        response.status, detail,
      )
    }
    if (textStage && detail.reason === 'timeout') {
      const budget = typeof detail.timeoutMs === 'number'
        ? `（本次上限 ${detail.timeoutMs} 毫秒，可在文本配置的「超时」中调大）` : ''
      throw new ApiError(
        `${textStage.label}：上游请求超时${budget}。${textStage.tail}请先核对调用记录，勿重复点击生成。`,
        response.status, detail,
      )
    }
    if (textStage && typeof detail.upstreamStatus === 'number') {
      const reasons: Record<string, string> = {
        invalid_parameter: '上游不接受请求参数',
        model_or_endpoint_not_found: '上游找不到模型或推理接入点，请复制供应商调用示例中的 model ID',
        model_not_enabled: '当前账号尚未开通该模型',
        authentication: 'API Key 鉴权失败',
        permission_denied: '当前 Key 没有请求权限',
        rate_limited: '请求受限，请核对供应商配额与频率限制',
        service_error: '上游服务异常',
        request_rejected: '上游拒绝请求，具体原因未能识别',
      }
      const reason = typeof detail.reason === 'string' ? reasons[detail.reason] : undefined
      const parameter = typeof detail.parameter === 'string'
        && ['model', 'response_format', 'stream', 'messages', 'max_tokens', 'thinking'].includes(detail.parameter)
        ? `，参数：${detail.parameter}` : ''
      throw new ApiError(
        `${textStage.label}：${reason ?? '上游拒绝请求'}（上游 HTTP ${detail.upstreamStatus}${parameter}）。${textStage.tail}`,
        response.status, detail,
      )
    }
    if (detail.stage === 'h3_poll' && ['VIDEO_TASK_CANCELLED', 'VIDEO_GENERATION_FAILED'].includes(error ?? '')) {
      const taskId = typeof detail.taskId === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(detail.taskId)
        ? `（任务号：${detail.taskId}）` : ''
      const outcome = error === 'VIDEO_TASK_CANCELLED' ? 'H3 视频任务已取消' : 'H3 视频任务生成失败'
      throw new ApiError(
        `${outcome}${taskId}。供应商未返回成功的视频结果，未自动重试。` +
        '请核对该任务的供应商记录及费用状态；重新生成会发起新的请求，可能再次计费。',
        response.status, detail,
      )
    }
    if (['h3_submit', 'h3_poll', 'h3_result'].includes(String(detail.stage))
      && error !== 'PROVIDER_INVALID_RESPONSE') {
      const stages: Record<string, string> = {
        h3_submit: 'H3 视频提交失败',
        h3_poll: 'H3 任务已提交，查询失败',
        h3_result: 'H3 任务已完成，视频下载失败',
      }
      const reasons: Record<string, string> = {
        authentication: '视频 API Key 鉴权失败，请核对视频配置中的 Key 和地址',
        permission_denied: '当前请求没有访问权限，请核对供应商权限或结果链接',
        endpoint_not_found: '请求地址不存在，请核对视频提交/查询路径或结果链接',
        request_rejected: '上游拒绝请求参数，请核对供应商调用记录',
        business_rejected: detail.stage === 'h3_submit'
          ? '网关未创建视频任务，并返回了业务拒绝'
          : '网关拒绝查询已有任务，不能据此判断视频是否生成成功',
        quota_exhausted: '视频供应商余额或额度不足',
        rate_limited: '视频供应商请求受限，请核对配额与频率限制',
        service_error: '上游服务异常',
        timeout: '请求超时',
        connection_error: '无法连接上游服务，请核对地址和网络',
      }
      const reason = reasons[String(detail.reason)] ?? '请求失败'
      const status = typeof detail.upstreamStatus === 'number'
        ? `（上游 HTTP ${detail.upstreamStatus}）` : ''
      const upstreamCode = typeof detail.upstreamCode === 'string'
        && /^[A-Za-z0-9_.-]{1,64}$/.test(detail.upstreamCode)
        ? `，错误类型：${detail.upstreamCode}` : ''
      const taskId = typeof detail.taskId === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(detail.taskId)
        ? `（任务号：${detail.taskId}）` : ''
      const tail = detail.stage === 'h3_submit'
        ? '请先核查供应商是否已有任务，勿重复点击生成。'
        : '请核查已有任务，勿重新提交生成。'
      throw new ApiError(
        `${stages[String(detail.stage)]}：${reason}${status}${upstreamCode}${taskId}。未自动重试。${tail}`,
        response.status, detail,
      )
    }
    if (error === 'PROVIDER_INVALID_RESPONSE') {
      const stages: Record<string, string> = {
        h3_text: '文本模型未返回可解析的扩写 JSON，尚未提交 H3 视频',
        h3_submit: 'H3 提交响应未返回可解析的任务信息，是否已创建任务尚不确定',
        h3_poll: 'H3 任务已提交，但任务查询响应无法解析',
        h3_result: 'H3 任务已完成，但结果地址无法解析',
      }
      const textReasons: Record<string, string> = {
        invalid_envelope: '文本服务的 HTTP 响应不是 JSON',
        message_missing: '文本响应缺少有效的 message',
        output_truncated: '文本模型的扩写输出被截断',
        empty_content: '文本模型未返回正文',
        reasoning_only: '文本模型只返回了推理内容，没有扩写正文',
        content_refused: '文本模型明确拒绝输出或触发了内容过滤',
        content_not_text: '文本响应的正文类型不是文本',
        invalid_json: '文本模型返回的正文不符合 JSON 格式',
      }
      const textReason = textReasons[String(detail.reason)]
      const message = detail.stage === 'h3_text' && textReason
        ? `${textReason}，尚未提交 H3 视频`
        : typeof detail.stage === 'string' ? stages[detail.stage] : undefined
      const count = detail.stage === 'h3_text' && typeof detail.contentCharacters === 'number'
        ? `（响应正文 ${detail.contentCharacters} 字符）` : ''
      const tail = detail.stage === 'h3_text'
        ? '文本请求可能已计费，未自动重试。请核查已有文本调用记录，勿连续重试。'
        : '请先核查已有调用记录，勿重复点击生成。'
      const taskId = typeof detail.taskId === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(detail.taskId)
        ? `（任务号：${detail.taskId}）` : ''
      throw new ApiError(
        `${message ?? '模型返回的数据结构无法解析'}${count}${taskId}。${tail}`,
        response.status, detail,
      )
    }
    if (error === 'VIDEO_PROMPT_TOO_LONG' && detail.stage === 'h3_prompt') {
      const size = typeof detail.promptCharacters === 'number'
        && typeof detail.maxCharacters === 'number'
        ? `（${detail.promptCharacters} 字符，上限 ${detail.maxCharacters}）` : ''
      const message = detail.textExpansionAttempted === false
        ? `原始对白、旁白及必需说明占用过多提示词空间${size}，请缩短台词或拆分镜头。未调用文本模型，尚未提交 H3 视频。未自动重试。`
        : `系统扩写后的完整提示词超出 H3 长度限制${size}，尚未提交 H3 视频。文本扩写可能已计费，未自动重试，请勿连续重试。`
      throw new ApiError(message, response.status, detail)
    }
    if (error === 'H3_PROMPT_INVALID') {
      const reasons: Record<string, string> = {
        duration: '扩写时长与当前镜头不一致',
        sections: '扩写 JSON 章节缺失、多余或类型不正确',
        shots: '画面描述缺少 [Shot 1] 镜头标记',
        dialogue: '扩写未按顺序完整保留原对白',
        narration: '扩写未按顺序完整保留原旁白',
        language: '英文描述中混入了未标记的中文',
        references: '参考图编号缺失或出现未提供的素材编号',
        subjects: '主体标签未定义或使用了不支持的场景标签',
        timing: '切镜时间重复、乱序或超出镜头时长',
      }
      const reason = typeof detail.reason === 'string' ? reasons[detail.reason] : undefined
      const sections: Record<string, string> = {
        subject_definitions: '主体定义', summary: '摘要', retention_analysis: '参考保留分析',
        detailed_description: '画面描述', integrated_multimodal_description: '画面描述',
        overall_soundscape: '环境音效', non_diegetic_music: '背景音乐',
      }
      const section = typeof detail.section === 'string' ? sections[detail.section] : undefined
      throw new ApiError(
        `Skill 扩写未通过校验${section ? `（${section}）` : ''}${reason ? `：${reason}` : ''}。未提交 H3 视频生成；本次文本扩写可能已计费，请勿连续重试。`,
        response.status, detail,
      )
    }

    if (error && apiErrorMessages[error]) throw new ApiError(apiErrorMessages[error], response.status, detail)
    throw new ApiError(error === 'PROVIDER_SCRIPT_LANGUAGE_INVALID'
      ? '模型未按要求返回中文剧本，已保留旧稿，未自动重试。'
      : error === 'CHARACTER_FIELDS_REQUIRED'
      ? '请先在角色模块补全角色名称、外观、服装和性格。'
      : error ?? `HTTP_${response.status}`, response.status, detail)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export const comicflowApi = {
  generateProjectReference: (projectId: string, kind: 'characters' | 'scenes', targetId: string, expectedVersion: number) =>
    request<{ reused: boolean; projectVersion: number }>(`/api/projects/${projectId}/references/${kind}/${targetId}`, {
      method: 'POST', body: JSON.stringify({ expectedVersion }),
     }),
  ...createCharacterApi(request),
  ...createStoryScriptApi(request),
  listProjects: () => request<Snapshot[]>('/api/projects'),
  createProject: (input: { story: string; durationSec: number; mode: WorkflowMode; stylePresetId?: string }) =>
    request<{ project: Project; guestSession: { id: string; projectId: string } }>(
      '/api/projects',
      { method: 'POST', body: JSON.stringify({ ...input, inputType: 'story' }) },
    ),
  uploadReferenceImage: (projectId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<{ asset: ReferenceImageAsset; projectVersion: number }>(
      `/api/projects/${projectId}/reference-image`,
      { method: 'POST', body: form },
    )
  },
  snapshot: (projectId: string) => request<Snapshot>(`/api/projects/${projectId}`),
  ...createVideoApi(request),
  ...createAudioApi(request),
  ...createCompositionApi(request),
  requestMagicLink: (email: string) =>
    request<{ email: string; token: string }>('/api/auth/magic-link', {
      method: 'POST',
      body: JSON.stringify({ email }),
    }),
  verifyMagicLink: (token: string) =>
    request<{ userId: string; email: string }>('/api/auth/verify', {
      method: 'POST',
      body: JSON.stringify({ token }),
    }),
  claimProject: (projectId: string) =>
    request<{ project: Project }>(`/api/projects/${projectId}/claim`, { method: 'POST' }),
  projectCredits: (projectId: string) =>
    request<{ available: number }>(`/api/projects/${projectId}/credits`),
  providerConfig: () => request<{ text: TextProviderConfigView; image?: MediaProviderConfigView; video?: MediaProviderConfigView; runtime?: ProviderRuntimeStatus; scope?: string; profiles?: Partial<Record<ProviderCapability, ProviderProfilesView>> }>('/api/provider-config'),
  saveProviderProfile: (capability: ProviderCapability, slot: ProviderSlot, profile: Record<string, unknown>) =>
    request<MediaProviderConfigView>(`/api/provider-config/profiles/${capability}/${slot}`, { method: 'PUT', body: JSON.stringify(profile) }),
  activateProviderProfile: (capability: ProviderCapability, slot: ProviderSlot) =>
    request(`/api/provider-config/profiles/${capability}/${slot}/activate`, { method: 'POST' }),
  deleteProviderProfile: (capability: ProviderCapability, slot: ProviderSlot) =>
    request<void>(`/api/provider-config/profiles/${capability}/${slot}`, { method: 'DELETE' }),
  saveMediaProviderConfig: (capability: 'image' | 'video', profile: Record<string, unknown>) =>
    request<MediaProviderConfigView>(`/api/provider-config/media/${capability}`, { method: 'PUT', body: JSON.stringify(profile) }),
  deleteMediaProviderConfig: (capability: 'image' | 'video') =>
    request<void>(`/api/provider-config/media/${capability}`, { method: 'DELETE' }),
  saveTextProviderConfig: (input: { provider: string; baseUrl: string; model: string; timeoutMs: number; enabled: boolean; apiKey?: string }) =>
    request<TextProviderConfigView>('/api/provider-config/text', { method: 'PUT', body: JSON.stringify(input) }),
  testTextProviderConfig: () => request<{ ok: boolean; model?: string }>('/api/provider-config/text/test', { method: 'POST', body: '{}' }),
  deleteTextProviderConfig: () => request<void>('/api/provider-config/text', { method: 'DELETE' }),
  generationSession: (projectId: string) => request<GenerationSession>(`/api/projects/${projectId}/generation-session`),
  updateGenerationSession: (projectId: string, action: 'pause' | 'resume' | 'cancel' | 'retry') =>
    request<GenerationSession>(`/api/projects/${projectId}/generation-session/${action}`, { method: 'POST', body: '{}' }),
  advanceGenerationSession: (projectId: string) =>
    request<GenerationSession>(`/api/projects/${projectId}/generation-session/advance`, { method: 'POST', body: '{}' }),
}
