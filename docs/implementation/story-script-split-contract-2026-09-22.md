# 15D 第一批：故事/剧本行为保持拆分

状态：2026-09-22第一小批已完成，见[验收记录](story-script-split-verification-2026-09-22.md)。7B已完成，本批仅故事/剧本，后续按固定顺序合成/导出、声音、拆分后完整不扣费回归。用户要求小心实施，不过度设计。

## 接口与职责

新增 production/story_scripts.py 的 StoryScripts，接收项目/角色仓储、当前请求的文本Provider、审核Provider、共享项目锁、模型配置revision，以及同步生成状态、追加事件、创建角色三个明确回调。不接收整个Pipeline，不反向导入Pipeline，不缓存请求级模型。原Pipeline公开入口保留，调用时构造模块并委托；生成会话跨阶段推进、媒体生成/采用、合成/导出留在Pipeline。

模块负责故事生成/流式归一/保存、剧本拆分/预览/提交/编辑/确认、镜头编辑及版本读取、剧本角色同步；历史guided入口一并搬迁，保留兼容但不恢复产品入口。既有script_preview、script_characters、script_assets和Provider/Skill直接复用，不重写提示词。

后端 api/story_scripts.py 复用已有APIRouter注册模式和请求级pipeline获取函数，保持路径、方法、请求schema、响应形状/状态码、权限顺序、幂等header及错误映射。前端 api/storyScripts.ts 复用request注入，client.ts组合导出原api对象；页面调用名和界面保持不变。

## 数据与失败行为

输入仍是原项目ID、文本/剧本、expectedVersion、idempotencyKey；输出为原project/script/storyText/preview/session形状。保留模型用途绑定/配置revision、共享锁生命周期、审核/额度台账、事件顺序、outbox、版本冲突、草稿不落库和候选提交的原行为。确认剧本不生图；文本失败不偷偷重试。现有短故事补固定段落、无效流式JSON改走非流式修复属于既有行为，本批保留并记为后置问题，不借拆分调整调用数或文案。

不加表/schema/Redis状态，不修改真实配置/数据，不重启业务服务，不发真实模型请求、不提交推送。原迁移工具改动保持在工作区，不混作本批新增成果。

## 验收

先保存当前受影响源码与HTTP OpenAPI作为私有本地基线；先跑同组故事/剧本、模型绑定、会话、角色交接与失效测试，再抽取并用同组回归。补充请求级Provider切换和共享锁的公开入口特征测试；完整后端、Ruff/Mypy及前端构建/相关页面Playwright验证。移动的方法和路由用原AST/HTTP schema复核，仅接线部分允许差异；不能仅凭AST或行数宣布业务通过。

前端页面测试使用mock HTTP，完整真实隔离数据栈仍按固定第3步验收。本小批完成后更新HANDOFF、任务书、工单15的子状态和验证证据，不将整个15D标为完成。
