# 11A 当前项目历史视频验收

日期：2026-09-18。用户暂停部署相关工作，继续本地功能任务。本批完成11A，不代表全部11完成。没有提交/推送/部署、真实模型调用、数据迁移或启动Worker/Beat。

## 使用与接口

打开已有项目 → 顶部「资源」。每页24条，可筛选镜头、类型和状态；预览、下载、重新获取链接、来源镜头均有实际行为。缺文件、无对象键、存储暂不可用分别提示，不重新生成。下载先取得链接，再点「保存视频文件」。浏览旧版不改当前采用版或合成输入。

GET /api/projects/{id}/video-resources：kind/status/shot_id/offset/limit，limit上限100；摘要白名单不含对象键、旧URL或Prompt。GET /api/projects/{id}/video-resources/{asset_id}/access?download=true：只允许项目内记录的对象键，HEAD后签名900秒，下载加attachment，两接口响应no-store。未授权403、记录不存在404、文件缺失404、未保存键409、存储故障503。S3的403不得当文件缺失。

模块：backend/src/comicflow/production/video_resources.py，pipeline转接和生成元数据、api/app.py只读路由、providers/s3.py和AssetStore扩展。前端features/resources/VideoResourcesWorkspace.tsx，App/AppShell、workspace store及样式。无需schema迁移。

## 数据边界

- 已有visualAssets包括valid=false旧版。新生成补createdAt和shotTitle，被新版本替代记superseded；已知时间倒序，缺失时间的旧记录按追加顺序倒序并显示未知。元数据列表不批量HEAD/签名。
- 只有明确candidate或input-changed/dependency-changed标记才显示相应状态；既有生成链未统一记录失效原因，未知旧版一律历史，不猜测。删除镜头的记录仍可访问文件，但禁用来源跳转。
- 合成文件键目前复用，只有当前exportManifest可列，不承诺找回历史成片。仅供应商URL的旧记录需要核查原任务。
- 授权沿用ownerUserId/X-User-Id开发身份契约，未认领项目沿用原规则；不宣称实现新的正式认证。
- 首尾帧只在选中预览时按需签名，封面缺失不妨碍视频播放；本批无卡片缩略图/自动抽帧。跨项目索引、Prompt/参考详情、卡片缩略图后续11B；采用历史版后续11C与03/04。
- 真实MinIO历史对象未盘点，线上仍是此前部署版本，不能用离线样本证明线上旧视频一定存在。

## 验证

首次RED：后端8项新接口测试因404失败，前端2项因缺少资源入口失败；加入实现后聚焦通过。补充S3 HEAD403/404、下载attachment、缺失封面、候选/明确过期筛选、26条分页和真实本机媒体验证。

| 检查 | 结果 |
| --- | --- |
| pytest backend/tests/test_video_resources.py backend/tests/test_s3_asset_store.py -q | 23通过 |
| 全量pytest backend/tests -q --tb=short | 672通过，3跳过 |
| ruff check backend/src backend/tests | 通过 |
| mypy backend/src/comicflow | 70源文件通过 |
| pnpm --dir frontend build | TypeScript与Vite通过 |
| node --test frontend/tests/*.test.mjs | 27通过 |
| pnpm --dir frontend exec playwright test | 58通过（新增资源页4项） |

后端使用忽略目录var/verification/video-resources-20260918/run_offline.py：清理业务环境、设置memory/mock、禁用基础设施smoke，阻断socket外联，仅放行Windows asyncio内部socketpair。跳过2项需要脱敏项目样本的H3测试和1项Docker基础设施测试；存在一个既有Starlette/httpx弃用警告。

前端VITE_API_PROXY_TARGET设为http://127.0.0.1:9，新增用例拦截全部业务API。用FFmpeg合成96×160、2秒测试视频，经本机随机端口临时HTTP服务提供，验证readyState/currentTime和下载字节相等；结束关闭服务。普通请求拦截不能覆盖浏览器下载，因此不用伪签名成功代替文件验证。新增用例全部业务写请求为0。旧用例未拦截辅助请求产生127.0.0.1:9 ECONNREFUSED日志，58项仍通过，没有连接真实API。

日志和桌面/390px窄屏截图保存在var/verification/video-resources-20260918/；回溯副本在var/change-backups/video-resources-20260918-192742/。不执行git reset来回溯，避免覆盖其他未提交工作。

## 后续

02先落实生成前准备单：从实际请求编译逻辑展示模型、768P等分辨率、参考图用途、对白、提示词处理路径，无模型调用即可预检。接着03持久化视频作业与04恢复界面，后续再做连续性和角色板质量。旧数据迁移、部署与真实画质验收另行执行。
