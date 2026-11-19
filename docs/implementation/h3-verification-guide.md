# MiniMax H3 真实 API 验证指南

## 概述

本指南说明如何运行 MiniMax H3 真实 API 验证，验证完整的视频生成数据流。

## 前置条件

### 1. 启动完整本地环境

H3 验证需要完整的 Docker 环境（包括 MinIO、PostgreSQL、Redis）。

**Windows：**
```bash
powershell -ExecutionPolicy Bypass -File scripts/start-local.ps1
```

**Linux/Mac：**
```bash
docker compose up -d
```

等待所有服务就绪（约 2-3 分钟）。

### 2. 环境配置

确保 `.env` 文件包含以下配置：

```env
# MiniMax H3
MINIMAX_API_KEY=<YOUR_MINIMAX_API_KEY>
MINIMAX_BASE_URL=https://cp.compshare.cn
MINIMAX_VIDEO_MODEL=MiniMax-H3
MINIMAX_SUBMIT_PATH=/minimax/v2/video_generation
MINIMAX_QUERY_PATH=/minimax/v2/query/video_generation/{task_id}

# Bailian (for text and image generation)
BAILIAN_API_KEY=sk-ws-...
BAILIAN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

# S3/MinIO
S3_ENDPOINT=http://127.0.0.1:19000
S3_REGION=us-east-1
S3_BUCKET=comicflow
S3_ACCESS_KEY_ID=comicflow
S3_SECRET_ACCESS_KEY=comicflow_dev_only
S3_PUBLIC_ENDPOINT=http://127.0.0.1:19000

# Provider Modes
PROVIDER_MODE=real
VISUAL_PROVIDER_MODE=real
TTS_PROVIDER_MODE=real
COMICFLOW_COMPOSITION_PROVIDER=ffmpeg
```

### 3. 检查服务状态

```bash
# 检查 API
curl http://127.0.0.1:18000/health

# 检查 MinIO
curl http://127.0.0.1:19000/minio/health/live

# 检查前端（可选）
curl http://127.0.0.1:5173
```

### 4. 检查积分余额

运行积分检查脚本：

```bash
cd backend
PYTHONPATH=src python ../scripts/test_minimax_h3_api.py
```

确保 `available_points >= 100`（单次验证预计消耗 20-50 积分）。

## 运行验证

### 方式 1：通过前端 UI（推荐）

1. 打开浏览器访问 http://127.0.0.1:5173
2. 创建新项目（guided 模式）
3. 输入简短故事（30秒，生成 2-3 个镜头）
4. 生成剧本
5. 确认剧本（自动生成角色参考图和场景背景图）
6. 依次生成前 2 个镜头的视觉资产
7. 观察：
   - 第一个镜头应该使用场景背景图作为首帧
   - 第二个镜头应该使用第一个镜头的尾帧作为首帧
8. 生成音频资产（可选）
9. 请求合成
10. 等待合成完成并导出视频

### 方式 2：使用验证脚本

```bash
cd backend
python ../scripts/verify_h3_integration.py
```

脚本会提示确认，输入 `yes` 后继续。

**注意：** 验证脚本需要修改为使用完整的生产环境 API，而不是内存运行时。

## 验证流程

脚本将执行以下步骤：

### Step 1: 创建测试项目
- 创建 30 秒短片项目
- 故事：简短测试场景

### Step 2: 生成剧本
- 调用文本生成 Provider
- 生成 2-3 个镜头
- 输出场景和镜头数量

### Step 3: 确认剧本
- 自动生成角色参考图
- 自动生成场景背景图
- 输出生成的资产 URL

### Step 4: 生成视觉资产（关键验证点）
- **镜头 1**：使用场景背景图作为首帧（t2va 或 i2va 模式）
- **镜头 2**：使用镜头 1 的尾帧作为首帧（i2va 模式，首帧级联）
- 提取并存储每个镜头的首帧和尾帧
- 记录 `cascadeFromShotId` 元数据

### Step 5: 生成音频资产
- 为每个镜头生成 TTS 音频
- 生成 lip sync 数据（如果适用）

### Step 6: 请求视频合成
- FFmpeg 合成视频和音频
- 优先使用视频资产（video > image）

### Step 7: 等待合成完成
- 轮询作业状态
- 最长等待 5 分钟

### Step 8: 导出到桌面
- 将视频保存到桌面
- 文件名：`comicflow_h3_test_<project_id>.mp4`
- 同时导出字幕和封面

## 输出文件

验证完成后，以下文件将保存到桌面：

```
~/Desktop/
├── comicflow_h3_test_<project_id>.mp4       # 视频文件
├── comicflow_h3_test_<project_id>.srt       # 字幕文件
└── comicflow_h3_test_<project_id>_cover.jpg # 封面图片
```

## 验证检查清单

手动检查生成的视频，验证以下内容：

### ✅ 视觉质量
- [ ] 视频分辨率正常（1080x1920）
- [ ] 画面清晰，无明显失真
- [ ] 色彩和风格一致

### ✅ 场景连贯性
- [ ] 镜头 1 的首帧使用了场景背景图
- [ ] 镜头 2 的首帧与镜头 1 的尾帧相似（首帧级联）
- [ ] 场景切换自然，无突兀跳跃

### ✅ 角色一致性
- [ ] 同一角色在不同镜头中外观基本一致
- [ ] 角色动作和位置符合逻辑

### ✅ 音视频同步
- [ ] 音频与视频时长匹配
- [ ] 字幕与音频同步
- [ ] 无明显延迟或错位

### ✅ 技术指标
- [ ] 文件大小合理（预计 5-20 MB）
- [ ] 播放流畅，无卡顿
- [ ] 格式兼容（H.264 + AAC）

## 故障排查

### 错误：CASCADE_FRAME_MISSING

**原因**：上一镜头没有生成尾帧（可能是 mock 模式或生成失败）

**解决方案**：
1. 检查第一个镜头是否成功生成为视频（mediaType == "video"）
2. 检查 `FrameExtractor` 是否正常工作
3. 检查 MinIO 中是否有尾帧文件

### 错误：PROVIDER_RESPONSE_INVALID

**原因**：MiniMax H3 API 返回格式不符合预期

**解决方案**：
1. 检查 API 响应日志
2. 验证 endpoint 和 API Key 配置
3. 查看 `minimax_h3.py` 的响应解析逻辑

### 错误：FFMPEG_COMPOSITION_FAILED

**原因**：FFmpeg 编码失败

**解决方案**：
1. 检查视频文件是否完整下载
2. 验证文件格式（应为 .mp4）
3. 查看 FFmpeg 错误日志

### 超时

**原因**：视频生成时间过长（超过 5 分钟）

**解决方案**：
1. 检查 MiniMax API 状态
2. 减少镜头数量（仅测试 1 个镜头）
3. 增加 `max_attempts` 值

## 预期结果

### 成功标志

```
========================================
Verification Complete!
========================================

📁 Output files saved to: ~/Desktop
   - Video: comicflow_h3_test_<project_id>.mp4
   - Subtitles: comicflow_h3_test_<project_id>.srt
   - Cover: comicflow_h3_test_<project_id>_cover.jpg

✅ Please review the video to verify:
   1. Visual quality and coherence
   2. Scene continuity (first frame cascade)
   3. Audio sync with visuals
   4. Subtitle timing
```

### 性能指标

- **总耗时**：3-5 分钟（取决于视频生成速度）
- **API 调用次数**：
  - 文本生成：1 次
  - 图片生成（角色参考 + 场景背景）：2-3 次
  - 视频生成：2 次（2 个镜头）
  - TTS 生成：2 次
- **积分消耗**：20-50 积分（预估）

## 下一步

验证成功后：
1. ✅ 标记任务 5 为完成
2. ✅ 更新 `../status/HANDOFF.md` 和 `minimax-h3-video-workflow.md`
3. ✅ 提交代码到 Git
4. ✅ 准备合并到 master 分支

验证失败后：
1. 收集错误日志和截图
2. 分析失败原因
3. 修复问题后重新验证
4. 不要多次重试以节省积分

## 重要提醒

⚠️ **积分管理**：
- 验证前检查余额
- 单次验证即可，不要重复运行
- 失败后先离线调试，再运行真实验证

⚠️ **数据隐私**：
- 不要在提交中包含完整 API Key
- 不要在日志中记录敏感信息
- 生成的视频内容仅用于测试

⚠️ **环境要求**：
- 必须在真实 Provider 配置下运行
- Mock 模式无法验证首帧级联
- 确保网络连接稳定
