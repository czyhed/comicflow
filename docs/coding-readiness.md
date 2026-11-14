# ComicFlow Coding Readiness

## 已冻结的产品决策

- 产品主链路是动态 AI 漫剧，不是静态图片幻灯片。
- 生产模型必须使用可部署在优云平台的免费模型或开放权重模型。
- Mock 只用于开发、测试和生产故障降级。
- 每个镜头是独立的动态生成与重生成单元。
- 配音、口型、动作、表情、字幕和镜头运动必须进入同一时间轴。

## 首轮实现边界

### P0

- `ShotSpec`：角色、场景、动作、表情、镜头运动、对白和目标时长。
- `DynamicVisualProvider`：生成动态视频候选和关键帧/封面。
- `TtsProvider`：生成中文配音、实际时长和词/音素时间信息。
- `LipSyncProvider`：只处理有对白且可见嘴部的角色。
- `Timeline`：保存视觉、动作、表情、口型、字幕、音乐和音效轨道。
- `ComposeJob`：先生成低清预览，确认后生成最终 MP4。

### 明确不在首轮

- 全身复杂编舞
- 无限多人同框
- 声音克隆
- 专业级逐帧剪辑器
- 付费闭源 API 作为生产依赖

## 生成顺序

```text
Script/Storyboard Confirmed
  -> ShotSpec
  -> TTS (dialogue shots only)
  -> Subtitle + Viseme Timeline
  -> Dynamic Visual Generation
  -> Lip Sync / Expression Drive
  -> Low-res Preview
  -> Final Compose
```

## 重生成契约

| 范围 | 重做内容 | 不应重做 |
| --- | --- | --- |
| `visual` | 动态画面、关键帧 | 配音、字幕、口型 |
| `audio` | 当前对白配音 | 背景动作、场景画面 |
| `lipsync` | 当前对白口型 | 配音、背景动作 |
| `shot` | 当前镜头全部资产 | 其他镜头 |

## 开始编码前的门禁

- Mock Adapter 能完成动态镜头、TTS 占位、口型占位和 MP4 导出。
- 失败、重试、取消、版本冲突和 Credit 结算已有领域测试。
- 优云模型能力清单包含模型版本、许可证、资源需求、最大时长和健康检查。
- 前端已能显示动态预览、动作轨道、口型轨道和独立重生成入口。
- 低清预览与最终导出使用同一时间轴版本，不重新推断动作和对白。
