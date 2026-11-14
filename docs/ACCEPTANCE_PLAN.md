# ComicFlow 验收计划

**目的：** 定义每个开发阶段的验收标准和测试方法，确保质量可控。

**使用规则：**
- 每个任务完成后必须执行对应的验收步骤
- 验收不通过不得进入下一阶段
- 所有验收步骤必须可重复执行

---

## 阶段 0：环境验收

### 目标
确保本地开发环境完整可用

### 验收清单

#### 0.1 基础设施启动
```bash
# 执行
docker compose up -d

# 验收标准
docker ps | grep comicflow  # 应看到 postgres, redis, minio 三个容器运行中
```

#### 0.2 数据库迁移
```bash
# 执行
uv run alembic upgrade head

# 验收标准
# 无错误输出，显示 "Running upgrade -> xxx"
```

#### 0.3 API 服务启动
```bash
# 真实栈由 docker compose 提供，API 容器映射到宿主 18000
# （compose 内部仍是 8000，宿主端口不同，见 docker-compose.yml）
docker compose up -d api worker beat

# 验收标准
curl http://127.0.0.1:18000/health
# 返回: {"status": "ok"}
```

> ⚠️ **不要用 `uv run uvicorn ... --port 8000` 做验收**。本机 8000 上的进程默认全 Mock
> Provider，会静默产出假资产，让人误以为流程已跑通。验收必须打 **18000** 的容器栈。

#### 0.4 前端启动
```bash
# 执行（在 frontend/ 下；pnpm 不在 PATH 时用 node_modules/.bin/）
VITE_API_PROXY_TARGET=http://127.0.0.1:18000 ./node_modules/.bin/vite --port 5173

# 验收标准
# 浏览器访问 http://localhost:5173 可以看到页面
# Console 无致命错误
```

#### 0.5 百炼 API 连接
```bash
# 执行
curl -X POST http://127.0.0.1:18000/api/provider-config/text/test

# 验收标准
# 返回: {"ok": true, "title": "...", "model": "qwen-plus"}
# 无 PROVIDER_UNAVAILABLE 或 PROVIDER_AUTH_FAILED 错误
```

### 完成标准
- [ ] 所有容器运行正常
- [ ] 数据库表结构创建完成
- [ ] API /health 返回 ok
- [ ] 前端页面可访问
- [ ] 百炼 API 连接成功

---

## 阶段 1：Automatic 模式端到端验收

### 目标
验证从创建到导出的完整流程可以走通

### 1.1 创建项目

#### 手动测试步骤
1. 浏览器访问 `http://localhost:5173`
2. 选择 "automatic" 模式
3. 输入测试故事（至少 50 字）：
   ```
   一个年轻的程序员在深夜调试代码时，发现屏幕上出现了一个神秘的对话框。
   对话框里的AI开始和他对话，告诉他一个改变世界的秘密。
   他必须在天亮前做出选择：是继续平凡的生活，还是踏上未知的冒险旅程。
   最终他选择了勇敢面对，按下了那个闪烁的按钮。
   ```
4. 选择时长：60 秒
5. 点击"创建项目"

#### 验收标准
- [ ] 项目创建成功，返回 project_id
- [ ] 浏览器跳转到项目页面
- [ ] 项目状态显示为 "story" 或 "story-generating"
- [ ] 无 5xx 错误

#### API 验证
```bash
# 获取项目快照
curl http://127.0.0.1:18000/api/projects/{project_id}

# 预期返回结构
{
  "project": {
    "id": "prj_xxx",
    "stage": "story",
    "input": {
      "mode": "automatic",
      "story": "...",
      "durationSec": 60
    }
  }
}
```

### 1.2 生成故事文本

#### 手动测试步骤
1. 在项目页面点击"生成故事"或自动触发
2. 观察生成过程

#### 验收标准
- [ ] 显示生成进度指示器
- [ ] 生成完成后显示扩展后的故事文本
- [ ] 项目状态变更为 "story-generated"
- [ ] 故事文本长度 > 原始输入
- [ ] 无 PROVIDER_TIMEOUT 或 PROVIDER_UNAVAILABLE 错误

#### API 验证
```bash
# 调用生成 API
curl -X POST http://127.0.0.1:18000/api/projects/{project_id}/story

# 验收返回
{
  "project": {
    "stage": "story-generated",
    "generatedStoryText": "..."
  }
}
```

### 1.3 拆分剧本

#### 手动测试步骤
1. 点击"拆分剧本"按钮
2. 等待剧本生成

#### 验收标准
- [ ] 剧本生成成功
- [ ] 包含 6-12 个镜头
- [ ] 每个镜头包含：title, dialogue/narration, visualDescription, action, emotion, shotSize, durationSec
- [ ] 场景与镜头引用关系正确
- [ ] 项目状态变更为 "script-completed"

#### API 验证
```bash
curl -X POST http://127.0.0.1:18000/api/projects/{project_id}/script/split

# 验收返回
{
  "script": {
    "title": "...",
    "scenes": [...],
    "shots": [
      {
        "id": "...",
        "title": "...",
        "dialogue": "..." OR "narration": "...",
        "visualDescription": "...",
        "durationSec": 5
      }
    ]
  }
}
```

### 1.4 确认剧本

#### 手动测试步骤
1. 查看生成的剧本
2. 点击"确认剧本"按钮

#### 验收标准
- [ ] 确认成功
- [ ] 项目状态变更为 "storyboard-ready"
- [ ] scriptConfirmedVersion 已设置

#### API 验证
```bash
VERSION=$(curl -s http://127.0.0.1:18000/api/projects/{project_id} | jq '.project.version')
curl -X POST http://127.0.0.1:18000/api/projects/{project_id}/script/confirm \
  -H "Content-Type: application/json" \
  -d "{\"expectedVersion\": $VERSION}"
```

### 1.5 生成视觉资产

#### 手动测试步骤
1. 点击"生成画面"或触发自动生成
2. 观察每个镜头的生成进度

#### 验收标准
- [ ] 所有镜头都生成了视觉资产
- [ ] 每个资产包含 URL 或 objectKey
- [ ] 项目状态变更为 "visual-completed"
- [ ] visualAssets 数组包含所有镜头

#### API 验证
```bash
# 获取项目快照，检查 visualAssets
curl http://127.0.0.1:18000/api/projects/{project_id} | jq '.visualAssets'
```

### 1.6 生成音频资产

#### 手动测试步骤
1. 触发音频生成
2. 观察 TTS 生成进度

#### 验收标准
- [ ] 有对白的镜头都生成了音频
- [ ] 每个音频包含 durationMs
- [ ] 项目状态变更为 "audio-completed"
- [ ] audioAssets 和 lipSyncAssets 已填充

### 1.7 合成导出

#### 手动测试步骤
1. 点击"导出"按钮
2. 等待 FFmpeg 合成

#### 验收标准
- [ ] 合成作业状态为 "succeeded"
- [ ] 生成了 3 个文件：video.mp4, cover.jpg, subtitles.srt
- [ ] 项目状态变更为 "exported"
- [ ] exportManifest 包含 downloads 链接

#### 视频质量验证
- [ ] MP4 文件可播放
- [ ] 视频分辨率为 1080x1920 (9:16)
- [ ] 时长接近目标时长（±10%）
- [ ] 有画面、有声音、有字幕
- [ ] 封面图可显示
- [ ] SRT 字幕格式正确

### 完成标准（阶段 1）
- [ ] 手动执行 3 次完整流程，成功率 100%
- [ ] 每次流程耗时 < 10 分钟
- [ ] 生成的视频符合质量标准
- [ ] 所有中间状态正确保存到数据库
- [ ] 刷新浏览器后项目状态可恢复

---

## 阶段 2：Import 模式验收

### 2.1 导入故事

#### 手动测试步骤
1. 选择 "import_story" 模式
2. 输入已有的完整故事

#### 验收标准
- [ ] 跳过故事生成阶段
- [ ] 直接进入剧本拆分
- [ ] 后续流程与 automatic 一致

### 2.2 导入剧本

#### 手动测试步骤
1. 选择 "import_script" 模式
2. 输入结构化剧本 JSON

#### 验收标准
- [ ] 跳过故事和剧本生成
- [ ] 直接进入剧本编辑/确认
- [ ] 后续流程正常

### 完成标准（阶段 2）
- [ ] Import 模式与 Automatic 都能走通
- [ ] 两种模式最终产物一致

---

## 阶段 3：错误处理验收

### 3.1 百炼 API 失败

#### 测试步骤
1. 临时修改 .env 中的 API Key 为无效值
2. 尝试创建项目

#### 验收标准
- [ ] 返回明确的错误码（PROVIDER_AUTH_FAILED）
- [ ] 前端显示中文错误提示
- [ ] 项目状态标记为失败
- [ ] 额度已释放

### 3.2 生成超时

#### 验收标准
- [ ] 超时后返回 PROVIDER_TIMEOUT
- [ ] 支持手动重试
- [ ] 重试不重复扣费

### 3.3 版本冲突

#### 测试步骤
1. 打开两个浏览器窗口
2. 同时编辑同一个项目

#### 验收标准
- [ ] 后提交的请求返回 VERSION_CONFLICT
- [ ] 不会覆盖先提交的修改
- [ ] 提示用户刷新后重试

### 完成标准（阶段 3）
- [ ] 所有错误场景都有明确提示
- [ ] 错误后可恢复或重试
- [ ] 无静默失败

---

## 阶段 4：性能验收

### 验收标准
- [ ] 60 秒项目完整流程 < 10 分钟
- [ ] 数据库查询 < 100ms
- [ ] API 响应 < 500ms (不含 AI 生成)
- [ ] 前端首屏加载 < 2s

---

## 单元测试验收

### 后端测试覆盖
```bash
# 执行测试
uv run pytest

# 验收标准
# 测试通过率 100%
# 核心模块覆盖率 > 80%
```

### 前端测试覆盖
```bash
# 执行测试
pnpm test

# 验收标准
# 构建成功
# 类型检查通过
```

---

## 集成测试验收

### E2E 测试
```bash
# 执行 Playwright 测试
pnpm --dir frontend test:e2e

# 验收标准
# 主要用户流程测试通过
```

---

## 最终验收（所有阶段完成后）

### 冒烟测试清单
- [ ] 环境启动无错误
- [ ] Automatic 模式端到端成功
- [ ] Import 模式端到端成功
- [ ] 错误场景都有正确处理
- [ ] 性能指标达标
- [ ] 所有单元测试通过
- [ ] 所有集成测试通过
- [ ] 代码符合规范（Ruff + MyPy）
- [ ] 文档与代码同步

### 产品验收
- [ ] 产品经理可独立完成完整流程
- [ ] 输出视频质量可接受
- [ ] 操作流程符合预期
- [ ] 错误提示清晰易懂

---

## 验收执行记录

### [日期] - 阶段 0 验收
**执行人：**
**结果：** ✅ 通过 / ❌ 失败
**问题记录：**

### [日期] - 阶段 1 验收
**执行人：**
**结果：** ✅ 通过 / ❌ 失败
**问题记录：**

---

## 文档更新记录
- 2026-09-07: 初始创建
