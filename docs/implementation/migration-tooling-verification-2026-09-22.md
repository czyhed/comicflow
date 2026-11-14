# 7B 迁移工具验收记录

日期：2026-09-22。固定计划第1步已完成：交付最小盘点/备份/恢复/校验工具，并在合成数据上通过隔离恢复演练。没有修改业务API或schema，没有迁移真实业务数据。下一项为15D故事/剧本拆分，之后合成/导出、声音，再做拆分后的完整流程回归；正式迁移仍暂停。

## 交付

- `scripts/migrate_data.py`：显式配置的四个CLI操作，报告路径防覆盖，异常输出受限代码。
- `scripts/migration_tools/inventory.py`：0004表/序列、全部配置历史解密、媒体引用、完整桶与Redis分类盘点。
- `scripts/migration_tools/bundle.py`：PostgreSQL共享快照备份，媒体SHA-256/元数据，主密钥独立副本，空目标保护及恢复后验证。
- `tests/deployment/test_migration_tools.py`：引用、未完成作业、备份路径、篡改、密钥、停写/目标声明和TLS策略测试。
- `tests/integration/migration-runtime.compose.yml`、`migration_port_proxy.py`、`verify_migration_runtime.py`：复用缓存镜像的专用数据栈和合成样本；不运行生产API/消费者。

使用方式和限制见[说明](migration-tooling-usage-2026-09-22.md)。不新增表、框架或迁移管理界面。

## 验证结果

| 检查 | 结果 |
| --- | --- |
| `uv run pytest backend/tests tests/deployment/test_migration_tools.py -q --tb=short` | 847通过，4跳过，3条既有弃用警告；业务后端无修改 |
| `uv run ruff check backend/src backend/tests scripts/migrate_data.py scripts/migration_tools tests/deployment/test_migration_tools.py tests/integration/verify_migration_runtime.py tests/integration/migration_port_proxy.py` | 通过 |
| `uv run mypy backend/src` | 86个后端源文件通过；不代表独立迁移脚本已做Mypy检查 |
| `uv run python -X utf8 tests/integration/verify_migration_runtime.py` | 最终修正版通过；7张表及自增序列、9个对象、2版加密配置恢复一致 |
| 新签名读取 | 9个媒体HTTP读取及字节比对通过，包括视频、参考图、尾帧、封面和字幕 |
| 仓储重建 | 重建2次，当前/候选/历史资源可读取，两版配置均可解密 |
| 外部影响 | 0真实模型调用、0业务数据读写、0Redis消息复制；未连接服务器、未重启业务服务 |

4项跳过：2项需要脱敏旧项目fixture、1项需要单独打开基础设施smoke开关、1项因本机符号链接权限不足。独立迁移基础设施测试已实际运行，不把跳过的smoke算作通过。

最终证据：`var/verification/migration-20260922-115722/rehearsal-report.json`，`passed=true`、`elapsedSeconds=15.25`。该时间为微型合成样本的一次运行，不包括真实传输/停写验收，不用来承诺迁移时长。本地目录还保留CLI报告、manifest和合成备份，均在Git忽略范围。

## 保护条件与修复过程

实际演练覆盖：额外schema表、未知视频作业、待发布outbox、Redis排队消息、缺失候选图、错误主密钥、损坏dump、源目标重合、目标非空库/桶/Redis、重复恢复。上传阶段强制失败后数据库已恢复，工具保留该部分目标；再次恢复被非空保护拒绝，不清空目标或源数据。

初始单测在工具缺失时RED；补查又先复现了额外schema漏检和盘点未应用TLS配置，修复为检查全部用户关系、明确当前模型配置自增序列并核对其状态，两个数据库客户端使用同一SSL配置。首次扩展关系检查漏纳已有自增序列，被真实数据库演练拦住，补齐后最终通过。

最早两次演练遇到Docker Desktop内部网络返回映射端口0；合成凭据的数据库认证失败，没有读取或写入业务数据。改为独立固定目标TCP代理发布随机回环端口，并在建连接前校验端口合法。之后成功完成四个CLI操作与恢复；失败尝试保留诊断，不冒充一次全部通过。

## 隔离与局限

专用项目 `comicflow-migration-rehearsal`，数据服务内部网络、PostgreSQL/MinIO临时文件系统；代理仅转发三个测试服务。宿主控制器使用合成配置和环境白名单，实际模型适配器未调用；不读取`.env`、业务卷或业务队列。CLI子进程没有全宿主防火墙隔离，不能将这次测试描述成所有进程绝对无外网。演练结束只清理该项目，不执行全局prune。

本批没有运行浏览器、完整业务API/Worker重启、正式服务器连通或真实模型质量验收；2次仓储重建不等于2次API进程重启。当前工具仅支持0004和未版本化专用桶；其他限制见使用说明。后续schema/存储契约改变须更新工具并重做对应演练。真实数据迁移、API只读验收与切换回退记录留在固定第4步。

## 交接

任务08按“工具及合成演练”完成；不将任务10正式迁移标为完成。源码检查点仍为 `b867b16`，固定计划提交为 `b940a24`；本批修改留在工作区，未追加提交或推送。下一批只处理15D故事/剧本职责，保持接口、参数、调用次数与持久化行为，不插入提示词/UI扩展。
