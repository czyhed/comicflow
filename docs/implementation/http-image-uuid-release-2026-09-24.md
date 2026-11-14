# 仅发布HTTP生图UUID修复

2026-10-08再次重试：按用户要求执行普通git push，失败于不可达的本地代理；命令级禁用代理的远端读取也被连接重置。GitHub API确认main仍为ef7e06c，commit statuses仍为空，当前凭据push=true/admin=false，hooks接口404。Drone仓库页面再次Not Found。本次未制造空提交、未改远端引用、未启动新构建。需要恢复Git网络，并由仓库管理员检查既有Webhook投递/Drone授权；重复推送相同提交不会补发缺失的通知。

按原流程再次核查：普通git push失败于本机已停止的127.0.0.1代理；仅本命令设置http.proxy为空后，github.com:443直连仍超时，未改全局配置。此前GitHub API发布已成功，仓库事件可见eba9e3a的PushEvent，远端main为ef7e06c。当前凭据仓库permissions为push=true、admin=false、maintain=false，hooks API返回404，无法据此核实通知是否投递。Drone已登录且仓库启用，但构建列表仍止于6；需要仓库管理员查看既有Webhook的Recent Deliveries，确认响应后重投对应main事件。不能把此状态误报为代码CI失败或部署成功。

最新续接：用户再次明确要求重新推送，已在原隔离worktree创建仅触发用途的空提交`ef7e06c4fb4796c763d4ea2906a48ceb452d6f06`，API校验并fast-forward发布至main，标签`deploy-20260924-image-uuid-retry`；代码树与eba9e3a完全一致。发布工具补充空提交直接复用父树，首次422发生于创建树、尚未更新远端，随后成功。Drone登录已恢复、仓库可读，但重推后列表仍止于构建6，GitHub statuses为空。另尝试一次New Build/main，弹窗关闭后仍无新构建记录，未确认触发成功；未修改流水线触发条件或仓库权限。后续应排查webhook/Drone触发链路，不再连续空提交。

2026-09-24。用户在说明服务器修复需要前端发布后，明确要求“先单独修复这个报错”，本批执行该单项前端发布，不包含流式输出和其他未发布改动。

## 发布范围

从GitHub API核对远端`leifengyang/comicflow-web/main`为上次成功的`4db450a4b40c21e043b74f371f2de1edbbccde18`（Drone 6）。基于此提交建立独立worktree：`var/releases/2026-09-24-web-uuid`，分支`codex/http-image-uuid-hotfix`。

仅三个文件：`frontend/src/operation-id.ts`、`frontend/src/features/characters/CharacterReferences.tsx`、`frontend/tests/e2e/character-image-workspace.spec.ts`。原生randomUUID不可用时用getRandomValues生成UUIDv4；主图、图生图板及文字板共用该修复，未知提交仍保留原操作ID。

未携带故事/拆分流式输出、UI美化、风格库或合成/视频入口的其他本地改动。后端、模型配置、API Key、数据库、MinIO、Redis与仙宫云均不更新，不调用真实模型验收。

## 验证和发布

独立发布包生产build、40项Node测试通过，三个文件凭据扫描和diff检查通过。浏览器禁用randomUUID复现HTTP能力条件，再验证三种图片用途。

Git直连只读查询遭连接重置，后续沿用已验证的GitHub API发布工具：校验远端基线、blob/tree/commit SHA并fast-forward更新main，不force push、不制造空提交。

已发布提交`eba9e3afa2b5d9aba7484fc6df45c74dbd4f08d5`，标签`deploy-20260924-image-uuid`。独立发布包81项Playwright、40项Node测试及生产build通过。不要重复推送或创建空提交。

截至本次检查，GitHub combined status为pending且statuses为空，服务器仍加载旧`index-B-ALBD9h.js`，与本次构建不匹配；`/nginx-health`和`/health`均200。记录见`var/verification/http-image-uuid-20260924/frontend.json`，其中`newFrontendVerified=false`，不能宣称上线成功。

Drone原会话可打开首页，但前端仓库及旧构建6均显示Not Found，SYNC报错。刷新登录后用户表示已登录，但代理可访问的Codex内置浏览器仍显示SIGN IN；随后登录跳转遭CDP超时，未能恢复构建访问。尚未触发或确认任何新构建。下一步恢复可操作的已登录Drone会话，核对目标提交的构建记录，再完成发布及线上验收，不重做源码修复。

线上无付费浏览器验证脚本`var/verification/http-image-uuid-20260924/verify-deployed.cjs`已准备，所有API均拦截为测试数据。当前旧版下三用途首个提交未发出，回归失败；新版本上线后需重跑并记录三用途UUID检查通过。未调用真实模型或修改业务数据。
