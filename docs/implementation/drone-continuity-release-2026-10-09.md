# 2026-10-09 Drone 发布

用户明确要求通过原 Drone 流程推送并尝试部署；本批先后端再前端。复用内部 comicflow 与 comicflow-web 仓库的 main/push、backend_external_env、comicflow-server / comicflow-web 和原外部数据服务。

## 最新：两仓 GitHub 推送完成

用户随后明确要求“先推送到GitHub”，本批改为先完成两仓推送，暂不继续手动触发或操作服务器部署。推送仍可能响应原main/push流水线。两仓远端 main 通过 GitHub API 再次核对：后端 `e1eebc3c3359143913301a31a7d9071f72a8b79e`，前端 `e47f2d45edac201e67c768d2f12fe5118aa54854`；前端标签 `publish-20261009-continuity-web`。均为fast-forward，逐项Git对象SHA一致，没有force push。私有配置、数据库备份、素材和本地诊断脚本不上传。

用户已称登录完成，但当前自动化会话仍未登录Drone，再次OAuth跳转超时，随后被用户中断。没有核实新构建或部署成功。后续恢复部署时先检查两仓是否已自动构建及服务器实际版本，尤其前端已推送，不能沿用下方“前端尚未推送”的历史状态。

## 发布准备

远端基线：后端bb2ac379（Drone8成功），前端ef7e06c4（UUID重推未触发，线上仍Drone6）。工作区保留，发布从白名单包合入独立克隆。Git网络克隆重置后使用已有完整历史的本地发布克隆创建独立目录，并再次核对GitHub远端main；不force push。

导出包265后端文件、102前端文件，凭据扫描通过；本地临时debug截图脚本不导出，业务源码/测试保留。发布当前已完成源码，包括文本等待、风格增量、UI整理、选中镜头合成、裁剪和可选严格尾帧接续。四处既有Ruff长行仅换行；前端完整回归复现拆分正文被进度组件隐藏，恢复正文同时保留阶段进度。

服务器schema0004_image_jobs、3项目/6角色/1视频作业/0图片作业；无pending/processing事件、无有效媒体租约、无活动合成，Worker idle。数据库custom备份44692字节、pg_restore目录读取通过，位于私有var/releases/2026-10-09-continuity/server-before.dump；不提交备份或配置。原数据/素材/密钥/模型配置和Redis命名空间保留，无schema升级、模型调用或迁移。

导出后端980通过/3条件跳过，Ruff/Mypy96通过，部署相关38通过。前端首次完整回归84通过/1失败，失败为隐藏流式正文，修正后85浏览器测试、53 Node测试及build/typecheck通过。

## 推送与触发状态

后端 main 已通过已有 GitHub API 发布工具 fast-forward 推送到 `e1eebc3c3359143913301a31a7d9071f72a8b79e`，标签 `deploy-20261009-continuity-backend`。逐一核对 blob/tree/commit SHA，远端 main 已验证；普通 Git 传输超时，没有修改全局代理配置。

2026-10-09 20:03（北京时间），Drone 仍显示后端构建8/旧提交 `bb2ac379`，新提交 GitHub 状态列表为空。New Build/main 只提交一次，表单关闭但未创建新构建，浏览器日志明确返回 `Bad credentials`。这是 Drone 关联 GitHub 凭据失效，不能当作构建或部署成功；不连续空提交。

已从 Drone 原账号登出并进入原 GitHub OAuth 登录入口刷新授权，当前停在 GitHub 登录页，等待用户完成登录。没有扩大授权范围或修改服务器配置。授权恢复后核对 main 最新 SHA，再触发一次并检查真实构建号、checks 和 deploy。

前端发布克隆 `var/releases/2026-10-09-continuity/web-publish` 已提交 `e47f2d45edac201e67c768d2f12fe5118aa54854`，父提交 `ef7e06c4fb4796c763d4ea2906a48ceb452d6f06`，尚未推送。后端部署成功并验收后再发布前端。此克隆缺少 origin/main ref，后续应先核对 GitHub 远端 main 未变化，再设置本地 tracking ref；不得强推远端。

服务器 `/health` 仍200，原版本继续服务。本批没有服务器容器更新、数据库升级、真实模型调用、数据删除或迁移。后续验收应检查 API/Worker/Beat 同版、前端静态资源与目标构建一致，不以推送成功代替部署成功。
