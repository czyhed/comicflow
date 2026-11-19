# ComicFlow 文档导航

> 本页是文档入口。仓库根目录的 `README.md` 说明本地启动；`AGENTS.md` 与工程规约说明协作约束。

## 开发入口

- [工程规约](PROJECT_ENGINEERING_RULES.md)：改动边界、测试门禁与领域规则。
- [领域词汇 CONTEXT](../CONTEXT.md)：项目、故事、剧本、场景、镜头、资产等术语。
- [架构与数据流](DATA_FLOW.md)：模块边界及业务数据流。
- [ADR 决策记录](adr/)：技术栈、运行时与架构决策。
- [README](../README.md)：环境要求、启动服务、常用命令。

## 产品与验收

- [PRD](product/prd.md)：产品范围与需求。
- [产品简介](product/product-brief.md)：产品定位。
- [验收计划](ACCEPTANCE_PLAN.md)：功能与发布验收标准。
- [项目演示指南](PROJECT_DEMO_GUIDE.md)：面向业务和技术同事的项目演示。
- [技术指南](PROJECT_TECHNOLOGY_GUIDE.md)：技术组件、请求路径与实现说明。
- [视觉风格指南](visual-style-guidelines.md)：视觉资产规范。

## 实施与运行

- [实施计划](implementation/)：阶段任务、实施记录与验证报告。
- [部署和 Drone 文档](DRONE_DEPLOYMENT.md)：发布流程、配置与部署核验。
- [Drone 提交手册](DRONE_SUBMISSION_RUNBOOK.md)：日常发布操作。
- [数据库迁移说明](DATABASE_MIGRATION.md)：schema 迁移规则。
- [数据迁移计划](DATA_MIGRATION_PLAN.md)：业务数据迁移边界与计划。
- [研究记录](research/)：技术评估与调查结果。
- [归档文档](archive/)：不再作为当前操作入口的历史资料。

## 状态与交接

- [交接文档](status/HANDOFF.md)：当前交接信息与最新进展。
- [阻塞项](status/BLOCKERS.md)：未决问题与依赖记录。
- [阶段行动计划](status/ACTION-PLAN.md)：阶段性任务安排。
- [H3 验证步骤](status/H3_VERIFICATION_STEPS.md)：专项验收操作记录。
- [集成完成记录](status/INTEGRATION_COMPLETE.md)：专项验收结论。

## 根目录中的协作文件

为保持现有脚本、链接和协作约定兼容，这些文件继续保留在仓库根目录：

- `AGENTS.md`：代理协作规则。
- `CONTEXT.md`：领域上下文（部分规范要求从根目录读取）。

> 面试准备资料不属于项目交付文档，将单独保存在仓库之外；产品演示与技术说明保留在 `docs/`。

## 维护原则

1. 新增架构决策写入 `docs/adr/`。
2. 新增实现过程与验证证据写入 `docs/implementation/`。
3. 部署操作写入 `docs/` 下对应部署文档。
4. 更新文档时同步修正引用链接；不为目录整洁迁移被现有约定依赖的根目录入口。
