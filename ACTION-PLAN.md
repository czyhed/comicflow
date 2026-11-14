# ComicFlow 快速落地行动指南

> **本文档是"当下怎么动手"的操作卡。** 规范和口径以 `docs/PROJECT_ENGINEERING_RULES.md`、
> `docs/DECISION_LOG.md` 为准；阶段划分见 `docs/TASK_PLAN.md`；验收步骤见
> `docs/ACCEPTANCE_PLAN.md`。三者冲突时以那三份为准。

## 🎯 核心目标
**用百炼平台跑通：故事 → 剧本 → 画面/配音 → 合成导出 的完整流程**

---

## 📋 启动与验证

### Step 1: 启动环境
```bash
# 一条命令：Docker 真实栈（api/worker/beat + postgres/redis/minio）+ 前端 dev
pwsh scripts/start-local.ps1
```

就绪后：
- API：http://127.0.0.1:18000
- 前端：http://127.0.0.1:5173

> ⚠️ **API 在宿主 18000，不是 8000。** 容器内是 8000，映射到宿主 18000
> （`docker-compose.yml` 的 `ports: ["18000:8000"]`）。
> **不要用 `uv run uvicorn ... --port 8000` 做验证**——本机 8000 上的进程默认全 Mock
> Provider，会静默产出假资产，让人误以为流程已跑通。这个坑已经骗过我们一次。

### Step 2: 确认打的是真实 Provider
```bash
curl http://127.0.0.1:18000/health
# {"status": "ok"}

curl -X POST http://127.0.0.1:18000/api/provider-config/text/test
# {"ok": true, "title": "...", "model": "qwen-plus"}
```

`.env` 里的开关决定真假，逐项确认（当前值）：
| 开关 | 当前 | 含义 |
|------|------|------|
| `PROVIDER_MODE` | `real` | 文本：真实 qwen-plus |
| `VISUAL_PROVIDER_MODE` | `real` | 画面：真实 wanx2.1-t2i-plus |
| `TTS_PROVIDER_MODE` | `real` | 配音：真实 qwen3-tts-flash |
| `MEDIA_PROVIDER_MODE` | `mock` | 其余媒体：Mock |
| `COMICFLOW_COMPOSITION_PROVIDER` | 见 `.env` | 合成：需为真实 FFmpeg 才产出可播放 MP4 |

> Provider 状态目前**在页面上看不见**（待办：可见化）。在此之前每次验收都要手动核对上表，
> 否则无法区分"流程跑通"和"Mock 假装跑通"。

### Step 3: 手动走完整流程
1. 浏览器打开 http://127.0.0.1:5173
2. 创建项目 → **automatic** 模式（`import_story` 已验过，`automatic` 未验）
3. 输入测试故事（≥50 字，用例见 `docs/ACCEPTANCE_PLAN.md`）
4. 时长选 **60 秒**（原始失败形状；30 秒/6 镜头已验过）
5. 逐阶段观察：故事 → 拆分剧本 → 确认 → 批量生成画面+配音 → 导出
6. **所有异常记录到 `BLOCKERS.md`**（含前端 Console + `docker compose logs api`）

---

## 🔍 已知的排查要点

### 导出被拒 409 `ASSETS_INCOMPLETE`
**这是正确行为，不是 Bug。** 响应体里带 `missingVisualShotIds` /
`missingAudioShotIds`，照单补齐对应镜头的资产再导出。此前没有这道门禁，半成品项目
也能导出，FFmpeg 用文字卡兜底，产出"只有文字"的片子。

### 批量生成慢
逐镜头**串行**执行，且 `projectVersion` 链式传递——并行会因乐观锁版本冲突互相打掉。
6 镜头约 2 分钟，10 镜头按线性估。慢是设计约束，不是性能缺陷。

### 拆分剧本 502
已修（模型省略未使用的可选键被误判违约）。若仍复现，注意**场景五字段**
（`time`/`location`/`narrativeGoal`/`conflict`/`turningPoint`）仍要求全部非空，属同类
未修缺陷，见 `docs/DECISION_LOG.md` 待决策事项。

---

## 🚫 当前阶段不做

1. **不重构 ProductionPipeline** —— 1812 行单文件问题已登记，等核心流程稳定
2. **不清理 guided 模式代码** —— 不影响 automatic/import 两条流程
3. **不做性能优化** —— 先确认正确性
4. **不扩大功能范围** —— BGM/音效、角色锁脸、文生视频接流水线都在后续队列

> 注意：**"不写测试"不在此列。** 根因修复必须带回归测试，这是工程规则第 ①
> 条（根因修复不打补丁）的一部分。本分支三处修复各自带测试。

---

## 📊 成功标准

### 最小可行标准
- 输入故事 → 60 秒内看到剧本预览
- 确认剧本 → 5 分钟内生成所有资产（10 镜头可放宽，串行）
- 点击导出 → 3 分钟内得到 MP4
- 视频**真的**可播放：有真实画面（非文字卡）、有配音、有字幕

### 验收检查清单
- [ ] 全程无手动干预（`automatic` 模式）
- [ ] 每个生成步骤有进度反馈
- [ ] 失败有明确提示（含缺失清单，不是裸错误码）
- [ ] 导出视频 1080×1920 / H.264+AAC / 时长接近目标 ±10%
- [ ] 抽帧确认是真实模型画面，不是占位图

---

## 🆘 遇到问题时

### 提供这些信息
1. 卡在哪个步骤
2. 浏览器 Console 错误
3. `docker compose logs --tail=100 api worker`
4. 当前 `.env` 的 Provider 开关（隐藏 API Key）

### 快速排查
```bash
# 1. 服务是否都在
docker ps --format "{{.Names}} {{.Status}} {{.Ports}}" | grep comicflow

# 2. API 健康
curl http://127.0.0.1:18000/health

# 3. 数据库表
docker exec comicflow-postgres-1 psql -U comicflow -d comicflow -c "\dt"

# 4. 最近日志
docker compose logs --tail=100 api worker
```

---

## 📅 后续队列

见 `docs/TASK_PLAN.md` 的阶段划分。摘要：
1. 补验未验项：浏览器实点批量生成 / `automatic` 模式 / 60 秒 10 镜头 / E2E
2. Provider 状态页面可见化（杜绝静默降级迷惑）
3. 契约健壮性：场景字段同类缺陷
4. 画质：风格统一、人物连贯、画面内禁文字
5. wan 文生视频接流水线 → BGM/音效 → 角色卡锁脸

---

## 💡 关键提示

**优先级：** 先让它**真的**工作 → 再让它稳定 → 再让它优雅。

**但"能跑"的判据必须硬：** 抽帧看画面、听配音、核对 Provider 开关。
兜底产物看起来也像"跑通了"——这正是上一轮被骗的方式。
