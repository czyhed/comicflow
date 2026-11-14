# 选中镜头合成

日期：2026-10-09。用户已明确授权实施；目标是让镜头素材尚未全部完成时也可以制作局部试片。

## 契约与实现

原 POST /api/projects/{project_id}/composition 增加可选 shotIds。省略时仍合成完整项目并保留全量素材门禁；提供时拒绝空、重复、不存在的镜头，按剧本order排序，只检查选中镜头的已采用画面与所需声音。镜头列表、相关资产及时间轴在深拷贝中筛选，不修改项目剧本或资产。

沿用composition作业、expectedVersion、idempotencyKey、权限、额度和outbox机制。Worker使用保存的shotIds构造FFmpeg输入，并再次检查素材。试片成功或失败均不修改完整exportManifest、项目stage、generationSession或downstreamInvalidated。内部额度沿用20，不等于供应商费用；合成不调用生成模型。

试片产物保存在 exports/{projectId}/previews/{jobId}/，清单保存在对应作业的exportManifest，包含scope=selected、shotIds和jobId。GET /api/projects/{project_id}/export?job_id={jobId}按当前项目所属作业读取并刷新签名；不带job_id仍读取完整成片。试片之间和完整成片的对象键独立，不覆盖原文件。

导出页新增“完整成片 / 选中镜头”模式、就绪镜头勾选、全选就绪/清空、独立合成按钮和已保存试片选择。只能选择已采用且素材齐全镜头；待采用候选不算就绪。试片记录刷新可找回，预览与下载读取对应作业，项目不会显示为完整成片已完成。沿用原视频/封面/字幕预览。

## 验证

- 后端全量：966通过、3条件跳过；隔离启动器清除业务环境并阻断真实网络。
- 聚焦后端：43通过，包含真实FFmpeg编码一秒带原声试片，ffprobe检查视频和音轨，验证未完成镜头不进入输出、完整导出不受影响。
- 页面相关：14通过，覆盖提交一次、就绪勾选、缺失素材阻断、刷新恢复、完整门禁及原声/旧流程；新增页面最后又通过1项聚焦检查。
- Node请求测试5通过、TypeScript/Vite构建、Ruff与相关Mypy通过。
- Playwright桌面/390px手机截图已检查，无横向溢出。页面使用拦截的测试API；预览媒体404是该fixture刻意返回的状态，不是生产媒体验证。
- 本地API与Worker已加载代码；重启前确认无有效媒体租约、无pending/processing outbox。OpenAPI确认shotIds和job_id参数存在，5173/代理health正常，Worker/Beat保持运行。

本批没有提交真实项目合成、调用模型、改模型配置、schema迁移、提交推送或服务器部署。数据库/MinIO/原解密密钥迁移及Redis正式切换任务继续保留。

## 使用与限制

导出 → 选中镜头 → 勾选就绪镜头 → 合成选中镜头。完成后可预览/下载，或在“已保存试片”中选择旧试片。原视频须足够长且包含所需音轨，否则保留FFmpeg原有错误，不自动补配音或延长视频。

选中范围按提交时项目版本校验，未加入“其他镜头变化仍可继续”的独立输入快照机制；字幕仍按镜头时长生成，不宣称语音逐句对齐。已有试片记录保留其历史输出，不能代表剧本后续修改后的最新内容。
