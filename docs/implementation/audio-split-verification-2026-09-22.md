# 15D 声音拆分验收

2026-09-22：本批完成，15D限定的故事/剧本、合成/导出、声音三批均已本地实现并回归。停止继续结构拆分，下一步按固定计划执行完整不扣费隔离回归。正式迁移部署仍暂停。

## 实现

`production/audio_production.py` 的AudioProduction负责配音、H3原声提取/复用、音频与口型资产失效、时间轴保存、单独口型重生成。只接收项目仓储、TTS Provider、口型Provider和可选资产存储，按当前调用构造；不传整个Pipeline，不新增回调、声音作业平台或表结构。

Pipeline保留原 `generate_shot_audio` 和 `_prepare_native_audio` 兼容入口；`regenerate_shot` 的scope校验、视频候选等待采用、audio/shot跨阶段分支原样保留，仅lipsync剩余分支委托 `regenerate_lip_sync`。后者的scope固定为lipsync，不生成音频；其他声音入口照旧处理对白/旁白、错误和版本。

H3继续复用本地native_audio实现及当前视频原声，不调用TTS/口型补救；原声提取后重读版本及视频有效性保持。自动阶段跳过H3独立配音、合成直接使用H3音轨、视频采用的声音失效逻辑都未重写。

`api/audio.py` 承接唯一的显式音频生成路由，仍通过请求当前Pipeline和原项目权限检查；局部重新生成路由保留在video路由。`frontend/src/api/audio.ts` 收拢原generateAudio请求；client导出名不变，测试加载器接入新模块。页面、模型配置、声音Provider协议和提示词没有修改。

## 验证

| 检查 | 结果 |
| --- | --- |
| 同组声音/媒体聚焦拆分前后 | 各38通过 |
| 完整后端及迁移工具 | 861通过、4条件跳过、3条既有弃用警告 |
| Ruff / Mypy | 通过，92个后端源文件类型检查通过 |
| 前端build / Node | 构建通过，27通过 |
| Playwright原声/生产/历史资源 | 17通过 |
| 方法比较 | 5个搬迁方法（含3个守卫）AST一致，局部口型分支与跨阶段分支逻辑一致 |
| Pipeline兼容 | 其余92个方法不变，3个受影响原方法签名不变 |
| HTTP/请求 | 完整OpenAPI73路径及schema一致，1条路由仅接线变化，1个前端请求不变 |

新增 `test_audio_module_contract.py` 共7个参数化展开用例，先在原实现通过再验证拆分：Provider请求副本与后续替换取当前依赖；口型重生复用音频并保留无关资产；口型失败不重试/不覆盖；无台词不调用模型；HTTP鉴权/版本冲突先于调用、配音及口型错误阶段可见。H3缺音轨、提取复用、并发编辑、真实音轨/运动保留由现有本机FFmpeg测试覆盖。

4项条件跳过分别是2项未提供本地脱敏H3输入、1项未启用Docker基础设施smoke、1项Windows符号链接权限不足。既有Alembic/Starlette弃用警告未在本批处理。首次聚焦命令带了不存在的候选测试文件，未运行测试；移除该路径后得到上述拆分前38通过。静态检查发现新模块import过长，换行后通过，没有因此改变方法行为。

主要命令：

```text
uv run --no-env-file python var/verification/audio-split-20260922/check.py backend/tests tests/deployment/test_migration_tools.py -q --tb=short
uv run --no-env-file ruff check backend/src backend/tests
uv run --no-env-file mypy backend/src
pnpm --dir frontend build
node --test frontend/tests/*.test.mjs
pnpm --dir frontend exec playwright test tests/e2e/native-audio-workspace.spec.ts tests/e2e/production-flow.spec.ts tests/e2e/video-resources.spec.ts --workers=2 --reporter=line
```

运行器不加载.env，清除继承的业务连接/密钥配置并禁止真实socket连接（仅允许Windows asyncio内部socketpair）；使用Mock、临时SQLite和本机FFmpeg。Playwright业务请求由测试拦截，预览进程代理设置为 `VITE_API_PROXY_TARGET=http://127.0.0.1:9`，浏览器播放测试媒体来自本机FFmpeg。未运行业务消费者或连接真实供应商。

## 证据、回溯与边界

修改前10份文件在 `var/change-backups/audio-split-20260922/`；OpenAPI和方法/路由/请求比较在 `var/verification/audio-split-20260922/`。这些私有目录保持Git忽略，新源码、测试和文档尚未提交。此前7B、故事/剧本及合成拆分改动保留，不用HEAD覆盖回溯。

本批保持旧行为，不宣称新增音频并发防重、音频持久作业或完整失败恢复。单独口型入口的错误映射/时长检查仍与普通配音入口不同；非H3配音未新增Provider返回后重读版本保护，Provider已有连接重试策略未改。这些是后续独立可靠性问题，不能将结构抽取视为已解决。合成作业原取消竞态/固定导出对象键等限制继续见合成报告。

真实模型调用0，未修改业务数据/运行配置、未重启业务API/Worker、未迁移数据、未提交推送或部署。当前业务容器不因此自动更新。

下一步固定第3步：使用假供应商和隔离PostgreSQL/Redis/MinIO/Worker/FFmpeg，完整验证拆分后的创建、剧本、角色板、相邻视频、采用、声音、合成、资源读取、导出和恢复。不继续按文件行数拆模块，不插入提示词/UI扩展，不要求用户重复付费验证满意的素材；完整隔离回归和真实30秒作品质量仍分别待验。
