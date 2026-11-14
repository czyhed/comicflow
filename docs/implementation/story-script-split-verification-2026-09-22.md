# 15D故事/剧本拆分验收

2026-09-22：第一小批完成，下一小批为合成/导出。整个15D尚未完成；声音和拆分后的完整隔离数据栈回归继续按固定计划推进。没有真实模型调用、业务服务重启、数据迁移、Git提交或推送。

## 实现

`production/story_scripts.py` 的 `StoryScripts` 收拢故事生成/流式处理/保存、剧本拆分与预览提交、编辑确认、镜头编辑、版本读取和剧本角色同步；保留旧guided方法兼容。原 `ProductionPipeline` 的18个操作入口委托到该模块，跨阶段会话推进及媒体生产留在流水线。

模块显式接收项目/角色仓储、当前文本/审核Provider、共享锁和模型配置revision，以及状态同步、事件追加、创建角色回调。每次从当前请求构造，不把模型选择缓存成旧Provider，不反向导入Pipeline。`script_preview`、`script_characters`、`script_assets`和原Provider/Skill直接复用。创建角色回调只承担原角色保存行为，不新增生成调用。

角色绑定仍调用Pipeline原 `_save_script_mutation` 入口，委托模块的 `save_script_mutation`，保持原版本更新和状态处理。原 `_validate_script` 保留兼容入口。三个短小仓储/版本/镜头守卫各自留在职责模块，没有为这次拆分引入公共基类或通用上下文。

`api/story_scripts.py` 收拢17条故事/剧本路由，复用原权限检查和请求级pipeline获取；错误映射、中间件和schema留在原位置。`frontend/src/api/storyScripts.ts` 收拢12个请求方法，`client.ts`继续暴露原 `comicflowApi`。页面代码、请求参数和响应类型未改。

## 验证和证据

| 检查 | 结果 |
| --- | --- |
| 拆分前后同组故事/剧本聚焦测试 | 各76通过；包含流式、版本、预览提交、编辑失效和角色交接 |
| 后端及已有迁移工具完整回归 | 849通过、4条件跳过、3条既有弃用警告 |
| `uv run ruff check backend/src backend/tests` | 通过 |
| `uv run mypy backend/src` | 88源文件通过 |
| `pnpm --dir frontend build` | TypeScript及Vite构建通过 |
| `node --test frontend/tests/*.test.mjs` | 27通过 |
| 创建/剧本预览提交/生产页面Playwright | 34通过；最终隔离补齐后15.1秒 |
| 方法与请求比对 | 31个搬迁方法AST逻辑一致；12个前端请求方法一致；完整OpenAPI的73个路径一致 |

完整回归命令：`uv run pytest backend/tests tests/deployment/test_migration_tools.py -q --tb=short`。4项跳过分别是2项缺本地脱敏H3样本、1项未开启基础设施smoke、1项符号链接权限不足。迁移工具的14个用例是上批成果，不能都算作拆分新增测试。

前端页面命令（frontend目录）：`pnpm exec playwright test tests/e2e/create-project.spec.ts tests/e2e/script-preview-commit.spec.ts tests/e2e/production-flow.spec.ts --workers=2`。页面使用mock HTTP，验证预览不落库、提交不重生、刷新恢复、故事流式显示、错误处理和下游操作入口；不是实际供应商、真实数据库或真实视频画质验收。

新特征测试 `backend/tests/test_story_script_module_contract.py` 先在旧实现通过，拆分后仍通过：请求浅拷贝与运行时切模型取到各自Provider，预览不写项目；共享锁拦截并发，完成后重复请求不再次生成/扣额度。现有全量模型绑定、持久化、会话、角色和视频测试同时保留。

本地代码/HTTP基线：`var/change-backups/story-script-split-20260922/`。比较记录：`var/verification/story-script-split-20260922/contract-comparison.json`、`client-comparison.json`。AST比较仅将 `_save_script_mutation` 的公开化名称统一后比较；不是仅以行数或AST代替运行测试。前端初次比较脚本误收集了嵌套的body字段，缩小到API方法后12项一致，未据此修改业务代码。

## 过程中发现的问题

第一轮抽取遗漏角色绑定对 `_save_script_mutation` 的调用，聚焦测试报错；补回原入口并委托新模块后同组76项通过。未改角色绑定的业务行为。

页面首轮34项通过，但旧创建页测试有未拦截的风格/轮询读取请求，尝试访问本机18002并被拒绝。已为该测试文件加统一兜底拦截，再跑34项通过且无该代理错误；未启动业务API解决测试问题。实际生成操作始终由mock处理。

## 保留行为和下一步

旧短故事补固定段落、流式JSON无效后进入原非流式修复路径均原样保留。这些属于后置行为/提示词问题；不能把本批描述为删除所有额外文本调用或修复所有内容质量问题。原镜头编辑与不同保存入口的失效语义也不在结构抽取中统一。

下一小批15D合成/导出：先锁定原输入、产物、幂等、错误、下载鉴权与原声处理契约，再抽取剩余职责；复用现有FFmpeg/原声模块。之后声音剩余职责，再做固定第3步完整不扣费隔离回归，正式部署仍暂停。本批没有更新运行中的业务API，不能把源码验收当作线上已生效。
