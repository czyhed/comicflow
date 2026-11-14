export const preflightErrors: Record<string, string> = {
  CONTINUITY_MODE_UNAVAILABLE: '严格尾帧接续需要 H3、同场景的上一镜头，且不能同时指定其他首尾帧。请改用常规参考或核对剧本。',
  VIDEO_SPEECH_OVER_BUDGET: '对白与旁白的总估算时长超过镜头时长。请在剧本中精简、拆分台词或自行调整时长，再刷新准备单。未调用模型。',
  VIDEO_JOB_CANDIDATE_STALE: '镜头、素材或模型配置已变化，此候选不能直接采用。请核对当前剧本和生成准备单。',
  VIDEO_JOB_CANDIDATE_MISSING: '候选视频文件不存在，请先检查对象存储。',
  VIDEO_JOB_NOT_ADOPTABLE: '当前作业没有可采用的候选视频。',
  VIDEO_PREFLIGHT_UNSUPPORTED: '当前适配器不支持视频准备检查，请配置 H3 或万相视频模型。未提交生成。',
  PREFLIGHT_STALE: '模型、剧本或参考素材已变化。请刷新生成准备单，核对后再提交。未调用模型。',
  REFERENCE_FILE_MISSING: '参考图片已不存在，请重新准备素材。',
  REFERENCE_STORAGE_UNAVAILABLE: '无法核对参考图片，请检查对象存储连接。',
  H3_REFERENCE_UNREACHABLE: '参考图仅有内网链接，无法供视频模型读取。请使用已保存的图片资产。',
  H3_REFERENCE_LIMIT: '参考图片超过 H3 的 9 张上限，请减少图片或使用角色整板。',
  H3_REFERENCE_MODE_CONFLICT: '首尾帧与普通参考图不能混用，请核对生成模式。',
  CASCADE_FRAME_MISSING: '上一镜头尚无可用尾帧，请先完成上一镜头及抽帧。',
  H3_DURATION_INVALID: 'H3 镜头时长须为 4–15 秒的整数。',
  H3_PROMPT_WRITER_REQUIRED: 'Skill 扩写尚未配置文本模型，请在模型管理中配置视频提示词用途。',
  H3_SKILL_UNAVAILABLE: '服务器缺少 H3 Skill 文件，请检查部署文件。',
  H3_PROMPT_TOO_LONG: '提示词超过模型长度限制，请精简镜头描述或台词。',
  VIDEO_DURATION_INVALID: '镜头时长不符合当前视频模型要求。',
  VIDEO_FIRST_FRAME_REQUIRED: '当前图生视频模型需要可用的首帧图片。',
  VIDEO_RESOLUTION_INVALID: '分辨率不符合当前视频模型要求。',
  VIDEO_MODE_UNSUPPORTED: '当前视频模型不支持此首尾帧或多参考图模式。',
  VIDEO_PROMPT_TOO_LONG: '提示词超过当前视频模型长度限制。',
  REFERENCE_IMAGE_INVALID: '参考图片格式或链接无效。',
}

export function preflightError(code: string) {
  return preflightErrors[code] ?? `准备未通过：${code}`
}
