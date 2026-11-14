# 视频一致性优化方案

## 问题描述

### 问题 1：画面割裂
- **现状**：每个镜头独立使用文生视频（t2v），镜头之间无关联
- **影响**：画面风格不一致，角色外观变化大，场景跳跃明显

### 问题 2：角色不一致
- **现状**：角色信息仅作为文本提示词附加到每个镜头
- **影响**：同一角色在不同镜头中外观差异大

## 解决方案

### 方案 A：首帧级联 + 角色参考图（推荐）

#### 流程设计

```
1. 角色设定阶段（新增）
   ├─ 为每个角色生成 1-2 张参考图
   ├─ 使用 wanx2.1-t2i-plus 或 qwen-image-3.0-pro
   └─ 保存到 S3，关联到角色 ID

2. 第一个镜头
   ├─ 输入：文本提示词 + 角色参考图
   ├─ 使用：wan2.7-i2v（图生视频首帧模式）
   └─ 输出：视频 + 提取尾帧

3. 后续镜头（级联）
   ├─ 输入：上一镜头尾帧 + 当前镜头提示词 + 角色参考图
   ├─ 使用：wan2.7-i2v（图生视频首帧模式）
   └─ 输出：视频 + 提取尾帧

4. 失败重试策略
   ├─ 单个镜头失败：仅重试该镜头
   ├─ 级联断裂：从断点重新生成
   └─ 全局失败：回退到独立 t2v 模式
```

#### 技术实现

**新增组件：**

1. **CharacterReferenceGenerator**
   - 根据角色卡生成标准参考图
   - 保存到 S3，返回 URL

2. **BailianImageToVideoProvider**
   - 支持首帧图片输入
   - 支持角色参考图（如果 API 支持）
   - 异步任务轮询

3. **FrameExtractor**
   - 从视频中提取尾帧
   - 使用 ffmpeg：`ffmpeg -sseof -1 -i input.mp4 -frames:v 1 output.jpg`

**修改组件：**

1. **Pipeline.generate_visuals()**
   - 第一个镜头：生成角色参考图
   - 镜头循环：使用上一帧作为首帧
   - 错误处理：级联失败回退

2. **Project Schema**
   - `characters[].referenceImageUrl`: 角色参考图 URL
   - `shots[].lastFrameUrl`: 镜头尾帧 URL（用于级联）

#### API 调用示例（推测）

```python
# 首帧生视频
POST https://dashscope.aliyuncs.com/api/v1/services/aigc/video-generation/image-to-video

{
  "model": "wan2.7-i2v",
  "input": {
    "first_frame_image": "https://...",  # 首帧图片 URL
    "prompt": "镜头描述文本",
    "reference_images": [  # 角色参考图（如果支持）
      "https://..."
    ]
  },
  "parameters": {
    "size": "1080*1920",
    "duration": 5
  }
}
```

### 方案 B：首尾帧控制（更精确，成本更高）

使用 wan2.7 的首尾帧模式，同时控制开始和结束画面：

```
输入：
- first_frame: 上一镜头尾帧
- last_frame: 当前镜头预期结束画面（需要额外生成）
- prompt: 运动描述
```

**优点**：运动轨迹更可控
**缺点**：需要生成更多图片，成本翻倍

### 方案 C：视频续接（探索性）

使用视频续接模式，直接从上一段视频延续：

```
输入：
- video_url: 上一镜头视频
- prompt: 续接内容描述
```

**优点**：理论上最流畅
**缺点**：API 成熟度未知，可能不支持长时间累积

## 实施计划

### Phase 1: 基础设施（1-2 天）
- [ ] 实现 FrameExtractor（ffmpeg 尾帧提取）
- [ ] 实现 CharacterReferenceGenerator
- [ ] 扩展 Project Schema 添加参考图字段
- [ ] 编写单元测试

### Phase 2: 图生视频 Provider（2-3 天）
- [ ] 研究百炼图生视频 API 文档
- [ ] 实现 BailianImageToVideoProvider
- [ ] 支持首帧输入
- [ ] 测试参考图功能（如果 API 支持）
- [ ] 集成测试

### Phase 3: Pipeline 集成（2-3 天）
- [ ] 修改 Pipeline.generate_visuals() 支持级联
- [ ] 实现角色参考图生成流程
- [ ] 实现首帧级联逻辑
- [ ] 错误处理和回退策略
- [ ] E2E 测试

### Phase 4: 优化和评估（1-2 天）
- [ ] 性能优化（并发、缓存）
- [ ] 质量评估
- [ ] 成本分析
- [ ] 文档更新

## 风险和降级策略

### 风险 1：API 不支持角色参考图
- **降级**：仅使用首帧级联，角色一致性通过提示词增强

### 风险 2：级联累积误差
- **降级**：每 N 个镜头重置一次（生成新的关键帧）

### 风险 3：成本过高
- **降级**：关键镜头使用 i2v，过渡镜头使用 t2v

### 风险 4：生成时间过长
- **优化**：并行生成非级联部分（如旁白镜头）

## 成功指标

1. **画面一致性**：同一场景的连续镜头色调和风格保持一致
2. **角色一致性**：主角在不同镜头中外观识别度 > 80%
3. **流畅度**：镜头切换时动作和位置合理衔接
4. **成本**：单个项目成本增加 < 50%
5. **时间**：总生成时间增加 < 30%

## 参考资料

- [百炼图生视频文档](https://help.aliyun.com/zh/model-studio/image-to-video-first-and-last-frames-guide)
- [Runway Gen-3 Image-to-Video](https://docs.dev.runwayml.com/)
- [Kling AI 图生视频](https://klingai.com/)
