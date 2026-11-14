# 阿里云百炼模型选型与免费额度核验

> 调研日期：2026-09-02。本文只引用阿里云百炼官方文档。模型名称、地域、价格和免费权益会变化；“免费”仅表示控制台当前可能提供新用户/活动赠送或模型标注的免费额度，不能作为长期成本承诺。上线前必须在目标账号、地域和模型详情页核对剩余额度与计费规则。

## 推荐结论

| ComicFlow 模块 | 首选百炼模型/服务 | 回退与说明 |
|---|---|---|
| 剧本拆解、分集大纲、角色卡 | `qwen3.8-flash`（质量优先可用 `qwen3.7-plus`） | 统一使用文本生成 API 的结构化 JSON 输出；保留 Mock Provider 做本地测试 |
| 角色/场景概念图、分镜首帧 | `qwen-image-3.0-pro` | 需要角色一致性时评测 `wan2.7-image-pro`；生成图片后持久化到 S3/MinIO |
| 动态镜头短视频 | `wan3.0-video`（同时评测 `happyhorse-1.1-t2v/i2v/r2v`） | 先以短片段和低分辨率评测；不可用时回退静态首帧 + FFmpeg 动效 |
| 中文配音 | `qwen-audio-3.0-tts-plus`（成本/速度优先可评测 flash） | 每段对白独立生成音频和时长；保留音色、语言、采样率配置 |
| 口型/说话头像 | 百炼模型目录中的视频/音频能力需逐项实测 | 百炼公开模型大全未承诺通用 lip-sync API；优先独立部署并评测 MuseTalk/Wav2Lip 等开源 Provider，审核许可证后再接入 |
| 内容安全 | 阿里云内容安全产品的文本/图片/视频审核服务 | 百炼模型目录未列出专用审核模型；审核阻止必须可观测且不扣除最终 Credit |

## 接入边界

FastAPI 只负责创建 Job、校验输入和保存 Provider 结果；真实推理放在 Celery GPU Worker 或独立推理服务。每个 Provider 需实现超时、重试、幂等键、错误分类和模型版本记录。任务输出先进入对象存储，再由合成任务生成预览或导出文件。

```text
剧本 -> TextProvider(qwen3.8-flash)
首帧 -> ImageProvider(qwen-image-3.0-pro)
短镜头 -> VideoProvider(wan3.0-video)
对白 -> TtsProvider(qwen-audio-3.0-tts-plus)
口型 -> 独立 LipSyncProvider（百炼能力可用后再替换）
文本/图片/视频 -> 阿里云内容安全 ModerationProvider
```

## 免费额度核验清单

1. 在目标百炼账号打开“模型大全/模型详情”，记录模型 ID、支持地域、输入输出限制、单价和免费标识。
2. 在“新人免费额度/活动权益”页面记录额度类型（当前规则通常按模型提供 Token 额度）、有效期、适用地域/模型和是否需要开通计费账户。当前官方说明为华北 2（北京）地域、有效期 90 天；仅实时推理抵扣，不含 Batch、调优、部署和 OSS，具体数量仍以账号页面为准。
3. 用实际 API Key 在 staging 做一次最小请求，核对响应中的 usage、任务状态和账单记录；不要以网页宣传数字替代账单结果。
4. 将额度耗尽、限流、模型下线和地域不可用映射为可重试或可回退错误，并在前端显示预计 Credit。

## 官方来源

- [百炼模型大全（功能规格与计费）](https://help.aliyun.com/zh/model-studio/models)：官方模型目录，覆盖文本、图像、音频和视频，并链接到模型详情与计费说明。
- [新人免费额度](https://help.aliyun.com/zh/model-studio/new-free-quota)：官方免费权益、适用地域、有效期和抵扣范围说明，以页面当前规则为准。
- [文本生成模型](https://help.aliyun.com/zh/model-studio/text-generation)：Qwen 文本模型调用、参数和结构化输出说明。
- [图像与视频模型](https://help.aliyun.com/zh/model-studio/image-model)：Qwen Image、Wan/Horse 图像与视频模型的能力说明。
- [语音合成模型](https://help.aliyun.com/zh/model-studio/tts-model)：Qwen Audio TTS 模型、音色和调用参数说明。
- [阿里云内容安全](https://help.aliyun.com/product/108806.html)：独立内容安全产品入口；不将其误写成百炼模型或百炼免费额度。

## 证据边界

本文没有声称任何模型永久免费、没有写入具体赠送数量，也没有声称百炼当前提供通用口型同步模型。真实模型接入属于任务 09 的评测工作：先确认账户权益、许可证、GPU/并发、普通话质量、镜头稳定性和数据合规，再把通过评测的 Provider 标记为生产默认。
