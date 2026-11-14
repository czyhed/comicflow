# H3 零额度验收记录

2026-09-10。按用户要求，暂停真实供应商验证；下列操作没有文本、图片或视频模型请求，不需要API Key。

## 已跑通的范围

读取当前项目 `prj_511e4e958ae7` 的六镜头剧本及角色元数据，去除签名参数后保存到 `.scratch/h3-offline/current-input.json`。只读读取原项目；测试在内存仓储创建独立项目，真实项目和已有视频不受影响。

`test_h3_offline_flow.py` 禁止 Python socket 连接；文本和H3请求使用MockTransport，真实Adapter与Skill校验器照常执行。标准双镜头样例和当前六镜头副本均完成：

1. API 接收镜头生成请求、流水线选择角色/场景参考。
2. 从测试存储读取PNG、按H3限制校验、转为Base64；文本仅收到标签和描述，不含图片内容/签名URL。
3. 文本Adapter解析模拟JSON，Skill校验旁白/对白、章节和引用。
4. H3 Adapter提交正确协议、查询任务、使用无鉴权下载客户端读取模拟结果。
5. 把本地FFmpeg生成的测试MP4写入隔离存储，真实FFmpeg提取JPEG首尾帧。
6. API刷新读回六个有效资产、预览地址、时长、对象键及Skill执行摘要。

模拟文本是测试fixture；视频是FFmpeg testsrc2测试画面。它们不是模型创作结果，也不会放进用户项目冒充真实视频。

## 发现并修复

- H3以前直接提交localhost参考图，还会先调用文本模型。现改为对象键读取并准备图片后再扩写。文件丢失、无对象键本机URL、格式/尺寸不合法、总大小超限均在第一次收费请求前拒绝。
- 图片正文与签名地址从文本上下文中移除，避免Base64进入LLM请求；视频请求仍包含完整图片。H3资产补充durationSec供下游使用。
- 原有分阶段错误诊断继续保留，不隐式重试、不跳过Skill。

官方依据：<https://platform.minimaxi.com/docs/api-reference/video-generation-v2-create>，媒体请求体最多64MB、单图30MB、256–5760像素及宽高比0.4–2.5；输入总量保守限定63MiB以预留JSON与提示词空间。使用当前已有PNG，不宣称所有图片格式均已支持。

另在临时新镜像容器内只读检查真实MinIO图片：角色PNG 1024×1536、2,099,305 bytes；场景PNG 1536×1024、2,100,204 bytes；均通过H3图片转换，合计Base64约5.22MB。模型请求0，数据库写入0。未把原图内容输出到日志。

## 重复执行

在仓库根目录PowerShell运行：

```powershell
$env:COMICFLOW_OFFLINE_FIXTURE='.scratch/h3-offline/current-input.json'
uv run pytest backend/tests/test_h3_offline_flow.py backend/tests/test_h3_preflight.py backend/tests/test_h3_validation.py backend/tests/test_h3_response_errors.py backend/tests/test_minimax_h3.py -q
```

需本地FFmpeg。缺少当前项目副本时默认测试跳过current-project案例，不等于该案例通过。不要运行test_minimax_h3_api.py或点击页面生成按钮代替离线验收，它们会发出真实请求。

验证：35项聚焦通过；Ruff、Mypy56文件、前端构建通过；全量342通过/12既有失败/1跳过，日志`.scratch/h3-offline/regression.txt`。12项失败与上一轮完全同名，包含旧级联/Script契约及参考图复用，不可称为整个项目全部通过。

## 尚不能证明

旧PROVIDER_INVALID_RESPONSE的真实响应已经缺失；用户确认优云没有新任务，但仅凭这一点不能判断文本JSON还是提交失败。离线测试能验证程序和协议处理，不能证明qwen一定返回合格扩写、优云网关一定接受请求或真实视频质量。真实验证继续暂停，必须等待用户后续明确授权。下一步优先修复12项现存离线失败与配置持久化；不得让用户连续付费试错。
