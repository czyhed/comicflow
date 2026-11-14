# 本地生成执行器恢复

日期：2026-10-09。用户反馈图片和视频一直排队，要求尽快恢复。

## 原因与处理

local-runtime-api-1 正常，但同一运行环境的 Worker / Beat 已停止。它们的 restart 已为 unless-stopped；该策略不会自动启动被手动停止的容器。仅重启前端/API不能恢复生成执行。

恢复前确认 API/Worker/Beat 的数据库、Redis、命名空间、MinIO 与密钥文件配置相同，专用 Redis 无积压消息和未确认消息。当前4条 pending outbox 涉及两条图片和一条新视频，均未调用模型、无供应商任务号及有效租约。备份后将这些事件保留为 held，作业状态和输入不变；历史 held 事件不释放。页面手动恢复会创建新的 pending 事件，可以继续原作业。

启动原 local-runtime-worker-1 和 local-runtime-beat-1，不重建容器、不迁移数据、不改变模型配置。没有启动其他历史验证执行器。

## 验证

- Worker control ping 返回 pong。
- 图片和视频各通过一次真实 Redis → Worker → 数据库查询往返；使用不存在的探测 jobId，返回 missing，在模型选择前退出，无真实模型调用。
- Beat 周期派发任务正常完成，空 outbox 返回0。
- 前端5173返回200，经前端代理的 health 返回ok。
- 已取消视频 vjob_a91bde48308b43629b1955841fb810b3 保持 cancelled，不恢复。

恢复前事件备份：var/verification/worker-restore-20261009/outbox-before.json。取消视频的状态与事件备份：var/verification/video-cancel-20261009/before.json。均保留于本机，未删除业务记录。

## 用户验证与边界

刷新页面后，图片点击“恢复已有图片作业”；新视频点击“继续处理已有作业”。用户点击恢复后会由原作业执行模型调用，可能计费，不要反复点击生成或批量恢复历史作业。新建生成作业也可按原流程派发。

本次只恢复本地执行环境，未验证真实供应商出图/出视频质量，未实现离线状态提示或修改启动脚本。后续完整启动必须包含当前命名空间的 API、Worker 和 Beat。没有服务器发布、数据库/MinIO/解密密钥迁移或Redis正式切换，相关任务继续保留。
