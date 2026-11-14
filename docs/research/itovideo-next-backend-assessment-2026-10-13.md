# 演示完成后的后端路线复评

日期：2026-10-13。状态：建议，未实施后端切换。用户本轮授权登录布局修复，并要求重新评估接入成本。

## 结论

首版演示已经完成，继续以现有独立演示运行。下一阶段若目标是任意故事、角色一致性和真实漫剧生产，建议保留 iToVideo 前端，通过兼容 API/前端数据适配层逐步调用 ComicFlow 现有业务；不把整套 ComicFlow 规则复制到第二个后端长期维护。此建议不撤销当前独立演示，也不授权修改旧业务数据。

前一份报告以最快复现全部可见页面为目标，推荐成套副本；这一步已经交付。当前比较的是下一阶段真实业务的增量成本，不是重新选择第一步。单纯继续改善演示内容和示例，现有副本仍最快。

## 本轮源码证据

| 功能 | 当前副本 | ComicFlow | 接入所需工作 |
| --- | --- | --- | --- |
| 画布保存 | `iToVideo_service/app/api/canvas.py` 和 `app/schemas/canvas.py` 保存 nodes/edges/viewport/version | `backend/src/comicflow/api/` 当前注册路由未提供 canvas/Studio 对等接口 | 保留或增加画布持久层；节点稳定映射业务角色/镜头；布局与业务版本分开 |
| 故事与剧本 | 原写作/归一化和 Studio 模板带商品语义；`app/services/executors/assisted/product_template.py` 固定 8/6/10 秒 | `api/story_scripts.py` 提供独立故事、剧本、确认、镜头增删和排序 | 用现有漫剧服务填充新界面，避免在 donor 再建一套角色/场景/对白契约 |
| 视频 | `src/canvas/hooks/useNodeRun.ts` 发送 nodeType/taskType/params/inputs，按 task.id 和任务状态更新 | `api/video.py` 和 `api/schemas.py` 按 shotId，expectedVersion/operationId/preflightFingerprint 提交；另有 recover/adopt | 适配请求、状态、结果和明确采用；不能把技术完成直接映射为已采用 |
| 角色 | 图片/素材节点 | `api/characters.py` 有角色卡、候选确认、整板确认、参考图作业与镜头绑定 | 保留视觉卡片，增加业务身份与候选交互；调用原角色能力 |
| 风格 | 配方内容、CRUD、收藏、应用和快照 | `api/app.py` 的 `/api/visual-styles` 提供画风目录 | 原配方能力不能全部映射为画风目录；保留配方存储，按用途抽取画风并保存业务快照 |
| 拼接与后期 | `src/pages/one-click/requests.ts` 的 compose/finalRequest 支持转场、输出规格、音轨和字幕；配套 FFmpeg 已验收 | `api/composition.py` 和 `api/schemas.py` 的 composition 接收版本、shotIds 和 shotTrims | ComicFlow 当前 composition 请求不是原后期编辑器的对等接口；初期保留原后期，之后扩展契约，不能丢音轨/字幕/转场 |
| 身份 | 本地固定 admin + 会话 token | `api/app.py` magic-link/verify 和项目权限校验；业务路由传 x_user_id | 正确衔接身份和权限；不能随便填用户 ID 来绕过校验 |

ComicFlow 的 ADR 0002/0005 仍要求持久化生产状态与既有作业架构。本轮只读源码，没有启动其服务、执行旧库迁移或调用供应商。

## 方案比较

| 路线 | 下一步成本 | 后续维护 | 建议 |
| --- | --- | --- | --- |
| 继续改 donor 成真正漫剧系统 | UI 改动较少，但需迁角色/剧本/作业/恢复等规则 | 容易维护两套相同业务 | 适合明确放弃原 ComicFlow 业务底座或继续演示；当前不优先 |
| 保留 UI，分段接 ComicFlow 能力 | 需适配模型与 API；画布自由节点和阶段流水线并非一一对应 | 漫剧业务保持一份，UI 专属状态独立保存 | 推荐下一阶段；先验证一条真实业务闭环 |
| 立即全部前端改接 ComicFlow，并移除 donor | 画布、配方和后期全部同时补接口，工作面最大 | 最终可归一，但短期演示易断 | 不推荐一次完成 |

自由画布若要求所有节点、任意连线均可执行，仅薄适配层不够：ComicFlow 目前基于项目/镜头流水线，需要明确支持哪些节点及输入语义。不能为了省适配把连线变成装饰。UI 保留也不意味着每个节点的生成语义完全零修改。

建议第一批固定最小业务范围：故事→剧本/角色→指定镜头→准备预览→作业→用户采用→原后期导出。保存 nodeId/shotId/assetId/jobId 的稳定映射；同一字段只有一个业务权威来源，不双向自动覆盖。画布布局、配方与原后期先保留；生成调用迁入后不能同时提交 donor 和 ComicFlow 两条作业。

当前源码证据支持这一排序，但没有完成兼容层试做，也没有实际工时/token测量，不能承诺固定天数或百分比。预期节省来自复用已有业务和限定接入范围；是否比定向搬规则更快，需首条闭环验证。

## 当前运行事实与本轮改动

- 账号 `admin`，密码 `admin`，由副本 `app/api/auth.py` 固定比较。
- 后端是独立 iToVideo 配套后端；数据库为 `127.0.0.1:55438/drama_demo`，并非 ComicFlow 或 donor 原库。媒体是独立本地 MinIO。
- 仅修改副本 `iToVideo_web/src/pages/LoginPage.tsx` 登录 CSS；修复竖版图铺满横屏导致的严重裁剪、窄屏表单挤压和短屏间距。未改登录行为和业务接口。
- TypeScript/Vite 构建通过；浏览器检查 1280×720、1280×600、1440×960、566×738、390×844。对应页面尺寸不超过视口；登录表单可见。截图在副本 `docs/screenshots/login-*.jpg`。
