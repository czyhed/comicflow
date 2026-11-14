# ComicFlow 项目文档导航

**最后更新：** 2026-09-07  
**当前阶段：** 阶段 0 - 环境验证与文档建立

---

## 📚 文档体系

### 必读文档（开始工作前必须阅读）

1. **[PROJECT_ENGINEERING_RULES.md](./PROJECT_ENGINEERING_RULES.md)** - 工程规约  
   **用途：** 每次修改代码前必读，定义了根因修复、测试门禁等核心规则  
   **关键内容：** 工程规则、阶段拆分、关键决策记录

2. **[CONTEXT.md](../CONTEXT.md)** - 领域词汇表  
   **用途：** 统一术语，避免命名混乱  
   **关键内容：** 项目、故事、剧本、场景、镜头、资产等核心概念定义

3. **[DECISION_LOG.md](./DECISION_LOG.md)** - 决策日志  
   **用途：** 记录每次重要技术决策，避免重复讨论  
   **关键内容：** 技术栈锁定、产品范围、架构决策

### 开发指南

4. **[DATA_FLOW.md](./DATA_FLOW.md)** - 数据流与架构  
   **用途：** 理解系统架构和数据流转  
   **关键内容：** 整体架构图、核心数据流、模块职责边界、接口契约

5. **[TASK_PLAN.md](./TASK_PLAN.md)** - 任务拆分与执行计划  
   **用途：** 指导当前阶段的具体任务执行  
   **关键内容：** 阶段划分、任务清单、验收标准、执行记录

6. **[ACCEPTANCE_PLAN.md](./ACCEPTANCE_PLAN.md)** - 验收计划  
   **用途：** 定义每个阶段的验收标准和测试方法  
   **关键内容：** 验收清单、测试步骤、完成标准

### 产品文档

7. **[prd.md](../prd.md)** - 产品需求文档  
   **用途：** 了解产品目标、用户旅程、功能需求  
   **关键内容：** MVP 范围、用户角色、页面需求、成功指标

8. **[product-brief.md](../product-brief.md)** - 产品简介  
   **用途：** 快速了解产品定位  
   **关键内容：** 产品概述、目标用户、核心价值

### 架构决策记录（ADR）

9. **[adr/0001-modular-monolith-with-worker.md](./adr/0001-modular-monolith-with-worker.md)**  
   **决策：** 采用模块化单体 + 独立 Worker

10. **[adr/0005-react-fastapi-python-stack.md](./adr/0005-react-fastapi-python-stack.md)**  
    **决策：** 技术栈选型（React + FastAPI + Python）

11. **其他 ADR** - 查看 `docs/adr/` 目录

### 临时文档（用于追踪当前问题）

12. **[BLOCKERS.md](../BLOCKERS.md)** - 阻塞点追踪  
    **用途：** 记录测试中发现的问题  
    **维护：** 随测试进度更新

---

## 🚀 快速开始

### 新人第一次接触项目

```
1. 阅读 README.md（项目介绍和启动步骤）
   ↓
2. 阅读 CONTEXT.md（理解领域术语）
   ↓
3. 阅读 PROJECT_ENGINEERING_RULES.md（了解工作规范）
   ↓
4. 阅读 DATA_FLOW.md（理解系统架构）
   ↓
5. 执行 TASK_PLAN.md 中的任务 0.2（验证环境）
```

### 开始新任务前

```
1. 查看 TASK_PLAN.md 确定当前任务
   ↓
2. 查阅 DECISION_LOG.md 相关决策
   ↓
3. 查阅 DATA_FLOW.md 相关模块
   ↓
4. 执行任务
   ↓
5. 按 ACCEPTANCE_PLAN.md 验收
   ↓
6. 更新 DECISION_LOG.md（如有重要决策）
```

### 遇到问题时

```
1. 记录到 BLOCKERS.md
   ↓
2. 查阅 DATA_FLOW.md 理解数据流
   ↓
3. 查阅 DECISION_LOG.md 查找历史决策
   ↓
4. 定位根因（不打补丁）
   ↓
5. 修复后更新文档
```

---

## 📋 当前状态

### 项目进度

- **当前阶段：** 阶段 0 - 环境验证与文档建立
- **已完成：**
  - ✅ 规范文档体系建立
  - ✅ 决策日志初始化
  - ✅ 验收计划定义
  - ✅ 数据流文档完成
  - ✅ 任务拆分方案确定

- **下一步：**
  - ⏳ 任务 0.2：验证基础环境
  - ⏳ 任务 1.1：手动执行完整流程
  - ⏳ 任务 1.2：问题分类与优先级排序

### 关键决策

**技术栈（已锁定）：**
- 前端：React 18 + TypeScript 5 + Vite 5
- 后端：Python 3.12 + FastAPI 0.116 + SQLAlchemy 2.0
- 数据库：PostgreSQL 16 + Redis 7
- AI 平台：阿里百炼 (DashScope API)

**产品范围（已确认）：**
- ✅ Automatic 模式（全自动生成）
- ✅ Import 模式（导入故事/剧本）
- ❌ Guided 模式（已废弃）

**当前目标：**
在本地环境跑通 Automatic 模式的完整流程

---

## 🔧 常用资源

### 启动命令

```bash
# 完整启动（推荐）：一条命令拉起真实栈 + 前端
pwsh scripts/start-local.ps1

# 或手动分步：
docker compose up -d              # 基础设施 + api/worker/beat（迁移由 migrate 服务自动执行）
cd frontend && VITE_API_PROXY_TARGET=http://127.0.0.1:18000 ./node_modules/.bin/vite --port 5173
```

> ⚠️ API 在**宿主 18000**（容器内 8000，见 `docker-compose.yml` 的 `ports: ["18000:8000"]`）。
> 不要用 `uv run uvicorn ... --port 8000` 做验证——本机 8000 上的进程默认全 Mock
> Provider，会静默产出假资产，让人误以为流程已跑通。

### 验证命令

```bash
# 健康检查
curl http://127.0.0.1:18000/health

# 百炼 API 测试
curl -X POST http://127.0.0.1:18000/api/provider-config/text/test

# 查看容器状态
docker ps | grep comicflow
```

### 测试命令

```bash
# 后端测试
uv run pytest

# 代码检查
uv run ruff check backend/src
uv run mypy backend/src

# 前端构建
pnpm test
```

---

## 📞 获取帮助

### 问题定位流程

1. **查看日志**
   - API 日志：终端输出
   - Docker 日志：`docker compose logs -f [postgres|redis|minio]`
   - 浏览器 Console：F12 开发者工具

2. **查阅文档**
   - 数据流问题 → `DATA_FLOW.md`
   - 历史决策 → `DECISION_LOG.md`
   - 验收标准 → `ACCEPTANCE_PLAN.md`

3. **记录问题**
   - 详细描述问题现象
   - 记录错误信息
   - 分析根因
   - 更新 `BLOCKERS.md`

---

## 📝 文档维护规则

### 何时更新文档

- ✅ 做出重要技术决策 → 更新 `DECISION_LOG.md`
- ✅ 修改架构或数据流 → 更新 `DATA_FLOW.md`
- ✅ 完成任务 → 更新 `TASK_PLAN.md` 执行记录
- ✅ 发现问题 → 更新 `BLOCKERS.md`
- ✅ 修复问题 → 更新所有相关文档

### 文档更新原则

1. **及时性：** 决策当天更新，不拖延
2. **完整性：** 包含背景、决策、理由、影响
3. **可追溯：** 标注时间、执行人
4. **简洁性：** 避免冗余，直击要点

---

## 🎯 核心原则（时刻牢记）

1. **根因修复，不打补丁**
2. **维护文档，避免遗忘**
3. **先定义，再拆分，后执行**
4. **技术栈锁定，不随意更改**
5. **本地优先，一步步落地**

---

## 版本历史

- **v1.0** (2026-09-07): 初始创建，建立文档体系

