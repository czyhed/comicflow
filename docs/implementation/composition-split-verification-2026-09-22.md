# 15D 合成作业与导出拆分验收

2026-09-22：本批本地完成。下一小批为声音剩余职责，随后完整不扣费隔离数据栈回归。整个15D未完成，正式迁移部署仍暂停。

## 实现与行为

新增 `backend/src/comicflow/production/composition_jobs.py`，收拢合成门禁、作业创建/执行/取消及导出清单。显式依赖项目仓储、合成Provider、可选资产存储和当前配置revision；从Pipeline每次调用时构造，避免请求副本或运行时切换使用旧依赖。不新增生成状态回调，原实现没有的Redis写入也不增加。

Pipeline原5个合成入口保持签名并委托新模块，Worker仍走 `pipeline.run_job`。FFmpeg、video_composition、native_audio和video_resources均复用。H3无独立音频也能合成，实际缺原声音轨仍报错；未添加TTS/口型兜底。内部20额度、原状态转换、claim、outbox、产物对象键和签名刷新逻辑保留。

新增 `api/composition.py` 收拢3条路由，保留原身份/项目/作业归属检查；新增 `frontend/src/api/composition.ts` 收拢2个请求，client对象名称不变。前端测试加载器补充模块解析，页面没有修改。

新增5个公开入口特征用例，在原实现先通过，验证当前Provider/revision与请求副本、导出签名刷新不改项目/不重合成、两种不完整产物失败、权限/幂等顺序和跨项目取消保护。已有合成与媒体测试复用。

## 验证结果

| 检查 | 结果 |
| --- | --- |
| 拆分前/后同组聚焦 | 各48通过 |
| 完整后端及迁移工具 | 854通过、4条件跳过、3条既有弃用警告 |
| Ruff | 全部通过（初次新增测试2处超长行，换行修正后通过） |
| Mypy | 90个后端源文件通过 |
| 前端构建 | TypeScript/Vite通过 |
| Node | 27通过 |
| Playwright合成/原声/生产/历史资源页面 | 17通过 |
| 原方法/接口比对 | 7个搬迁方法含守卫AST一致，Pipeline其他89个方法不变，5个原方法签名一致 |
| HTTP/前端比对 | 完整OpenAPI73路径及schema一致；3条路由仅接线变化，2个前端请求内容一致 |
| Git差异检查 | 无空白错误；未提交或推送 |

完整回归范围为 `backend/tests tests/deployment/test_migration_tools.py`。4项跳过：2项缺本机脱敏H3样本，1项未启用基础设施smoke，1项本机符号链接权限不足。不是全部真实基础设施验证通过。

本地运行器 `var/verification/composition-split-20260922/check.py` 清除继承的业务环境变量，不加载.env，禁止测试进程外部socket；只允许Windows asyncio内部socketpair。现有测试通过Mock/临时SQLite/本机FFmpeg运行。HTTP用ASGI内存请求，不连接业务API；前端相关测试拦截业务请求，预览代理指向关闭端口。浏览器资源测试使用本机合成视频，未生成供应商视频。没有启动Celery消费者。

主要命令：

```text
uv run --no-env-file python var/verification/composition-split-20260922/check.py backend/tests tests/deployment/test_migration_tools.py -q --tb=short
uv run --no-env-file ruff check backend/src backend/tests
uv run --no-env-file mypy backend/src
pnpm --dir frontend build
node --test frontend/tests/*.test.mjs
pnpm --dir frontend exec playwright test tests/e2e/native-audio-workspace.spec.ts tests/e2e/production-flow.spec.ts tests/e2e/video-resources.spec.ts --workers=2 --reporter=line
```

Playwright执行进程设置 `VITE_API_PROXY_TARGET=http://127.0.0.1:9`。上面的本地check运行器位于Git忽略的证据目录；新特征测试和产品代码在工作区，尚未提交。

## 回溯、限制与后续

本批修改前的10份文件基线在 `var/change-backups/composition-split-20260922/`，包含此前未提交成果，不能用Git HEAD覆盖它们。OpenAPI、方法、路由和请求比较证据在 `var/verification/composition-split-20260922/`。故事/剧本和迁移工具的既有改动仍保留，未算作本批新增实现。

结构抽取不等于加强原作业状态机。原合成取消不终止正在运行的FFmpeg；执行结束保存快照与取消交错、请求幂等的并发原子性、固定导出对象键覆盖等既有限制本批未改，也未声称已验收为并发安全。已覆盖原claim防重复消费、queued取消、失败重复执行仅一次释放；上述更强保证需独立缺陷验证后处理。

下一批声音模块应同时抽取 `generate_shot_audio`、`_prepare_native_audio` 和 `regenerate_shot` 的口型重生成分支；跨阶段协调继续归Pipeline。完成后按固定计划做完整真实隔离PostgreSQL/Redis/MinIO/Worker/FFmpeg贯穿回归，不能以本批Mock页面测试代替。

本批真实模型调用0；未修改业务数据/配置、未重启业务API/Worker、未迁移数据库、未推送或部署。源码已验收不代表当前业务容器已更新；无需为本次结构抽取重复付费验证满意的图片或相邻镜头。
