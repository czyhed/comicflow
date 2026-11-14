# 模型 Provider 选择策略

## 状态

Accepted for evaluation

## 决策

ComicFlow 按能力选择 Provider，不在生产流水线中直接依赖供应商 SDK。首轮真实 Provider 评测优先使用阿里云百炼的 OpenAI 兼容接口和模型服务；模型是否有免费额度、额度有效期、区域可用性和商用许可必须以项目负责人账户和百炼控制台在接入时核验。

| 能力 | 首选候选 | 回退 | 当前状态 |
| --- | --- | --- | --- |
| 故事/剧本 | `qwen-plus` | `MockTextProvider` | 待百炼账户核验 |
| 图片/关键帧 | 百炼 `wanx` 图像模型 | `MockDynamicVisualProvider` 的静态/2D 回退 | Adapter 边界已完成，接口与额度待核验 |
| 动态镜头 | 百炼 Wan 视频模型（以控制台可用模型 ID 为准） | `2d-motion` | 异步 Adapter 已完成，待 GPU、时长和并发评测 |
| 中文 TTS | 百炼 Qwen TTS/CosyVoice 可用模型 | `MockTtsProvider` | TTS 元数据 Adapter 已完成，待声音目录与许可核验 |
| 口型 | 独立部署 MuseTalk 或 Wav2Lip | `MockLipSyncProvider` | 资产元数据 Adapter 已完成，待模型与许可核验 |
| 内容审核 | 百炼内容安全/文本审核服务 | 生产门禁拒绝或人工复核 | 审核 Adapter 已完成，待账号、区域和数据合规核验 |
| 合成 | 本地 FFmpeg | 无 | 由系统控制，不交给模型 |

候选名称不是已接入的供应商契约。真实适配器必须实现现有 `TextProvider`、`DynamicVisualProvider`、`TtsProvider`、`LipSyncProvider` 和 `CompositionProvider` 接口，并记录 `provider`、`model`、`configVersion` 和请求引用。

2026-09-17 增补：按用户授权，连接凭据可经模型控制台提交至服务端，以 Fernet 密文保存于 PostgreSQL；主密钥独立来自服务器环境/Drone Secret 或共享的受保护密钥文件。前端只回读配置状态，不读取凭据。环境配置仍可用于初始化，模型库通过显式导入迁移；API 与 Worker 使用同一目录及版本快照，参数 JSON 不能替代尚未实现的协议适配器。详见 `docs/implementation/persistent-model-console.md`。

## 评测门禁

任务 09 已建立固定样例和指标报告契约，但真实账号评测尚未完成。必须用中文双角色样例集验证结构化输出、普通话质量、角色一致性、动作稳定性、时长、显存、并发、失败重试、许可证和单位 Credit 估算。评测通过后才允许把 `PROVIDER_MODE` 从 `mock` 切换到真实 Provider；未通过时继续使用 Mock 或局部 2D 回退。

## 后果

该策略保留供应商替换能力，也允许先用百炼免费试用额度做小样本评测。免费额度不等于服务器、GPU、带宽和对象存储免费，因此不会改变任务 08 的 Credit 与发布门禁。
