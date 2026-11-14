# 自定义模型与图片 503 修复

> 2026-09-12 路由可见性增量：`GET /api/provider-config` 现在返回当前图片 `imageAdapter`、`imageModel` 和 `imageProtocol`，模型 API 页面也直接显示这三个值。模型名称不会自动选择 Provider；`image-2.5` 只有在其服务实际提供 OpenAI 兼容图片协议时，选择 `openai-image` 才会走 `OpenAIImageProvider`。仍选择 `bailian-image` 时会按万相协议发送。该 OpenAI 兼容 Adapter 目前只支持文生图，三视图仍需 `wan26-image` 图像编辑协议。此次只做离线路由验证，没有真实模型调用。

日期：2026-09-09。用户要求所有文本、图片、视频模型自己填写、切换，不代替用户选择推荐模型。

## 配置方法

打开“模型 API”，在对应能力选择要编辑的测试/正式配置，填写模型名称、API 地址、密钥、参数并保存；只有当前套保存立即生效，备用套另点切换。所有模型名称都是自由文本，候选列表仅供参考。切换供应商保留手填模型和地址，但跨供应商/域名必须填写对应密钥。

按接口格式选择协议，不以模型名称猜测任意供应商的 API 格式：

| 能力 | 已实现协议 | 可自行填写 |
| --- | --- | --- |
| 文本 | Chat Completions 兼容接口 | 供应商、模型/部署别名、基础地址、密钥、超时 |
| 图片 | 万相文生图 V2、万相 2.6 图文异步协议 | 模型/别名、地址、密钥、尺寸、超时、图片协议、提交/查询路径 |
| 视频 | 百炼万相、优云 MiniMax H3 | 模型/别名、地址、密钥、超时、协议对应的输入模式/分辨率、提交/查询路径 |

这不是任意模型 API 的 JSON 转换器。OpenAI Images、其他平台私有协议、尚未接入的新版协议需要对应 Adapter；不能因为名称可填写就声称协议已兼容。TTS、口型仍按现有环境配置，不在本次文本/图片/视频编辑器范围。

## 如何确认 image-2.5 的实际路由

1. 打开“模型 API 配置”→“角色 / 场景图片 API”。
2. 查看配置卡片顶部的“适配器”和“协议”，它们代表当前 active 配置实际使用的代码路径。
3. 如果你的 `image-2.5` 服务返回 OpenAI 兼容图片响应，Provider 选择“OpenAI 图片”，模型填 `image-2.5`，地址填写该服务的 API 根地址。
4. 如果 Provider 选择“百炼万相”，即使模型字段填 `image-2.5`，仍然由 `BailianImageProvider` 按万相协议调用；这不是模型自动切换失败，而是 Provider 配置的明确结果。

图片“按已知模型匹配”只选择协议，不改变模型名：wan2.6-image → wan26-image；已知 2.2/2.1/2.0 t2i → wan-v2。自定义别名应手动指定兼容协议；旧别名在 auto 下沿用 V2 以兼容已有配置。明确冲突的已知模型/协议会拒绝保存，旧配置不变。显式协议允许任意自定义模型名，但实际兼容性与账户权限仍待供应商验证。

图片和百炼视频增加 `requestPath` / `statusPath`，相对 API 地址拼接；留空使用协议默认值。查询路径必须包含 `{task_id}`，不允许绝对地址、协议相对地址、反斜杠跨域。H3 继续使用原有 `submitPath` / `queryPath`。路径只改变路由，不改变请求或响应 JSON 格式。

## 当前 wan2.6-image 配置

- 供应商：百炼万相异步图片。
- 图片协议：万相 2.6 图文 / 兼容接口（或者按已知模型匹配）。
- 模型名称：`wan2.6-image`，使用用户填写的名称，不替换成 flash。
- API 地址：用户所属地域地址；北京现有地址为 `https://dashscope.aliyuncs.com/api/v1`。
- 尺寸：当前 `720*1280` 在官方 2.6 图文输出范围内。
- 提交/查询路径留空即可，默认 `/services/aigc/image-generation/generation` 和 `/tasks/{task_id}`。

角色与场景入口没有输入参考图片，因此此协议使用 `input.messages`、`enable_interleave=true`、`n=1`、`max_images=1`；从异步成功结果的 `output.choices[].message.content[].image` 读取图像，解码后保存 PNG。图像编辑所需 1–4 张输入图尚未接入该入口。每次最多生成一张，无隐式重试，不额外调用文本 API。H3 的 Skill 规则不变。

环境初始化也支持 `IMAGE_PROVIDER_PROTOCOL`、`IMAGE_PROVIDER_SUBMIT_PATH`、`IMAGE_PROVIDER_QUERY_PATH`；空路径采用协议默认值。Docker 已传递这些环境变量。页面配置仍不持久化、不共享到已有 Worker。

## 503 证据与修复

当时 API 日志记录两次角色参考图 POST 返回 503，图片启用，测试套模型 wan2.6-image。旧 Adapter 将所有图片模型发往 V2 image-synthesis，且把所有 HTTPError 映射成 PROVIDER_UNAVAILABLE / 503。官方 wan2.6-image 使用另一条 messages 协议，确认存在配置与请求格式不匹配。

用户没有上游 Response，旧日志也未记录，因此无法断言两次请求的真实上游错误是 400、401 或其他状态。离线通过真实角色 API → Pipeline → 图片 Adapter 模拟上游拒绝，复现 503；修复后按鉴权、参数、额度、限流、内容审核、下载失败返回对应中文提示。HTTP 错误日志只记录状态与应用错误码，不记录密钥、提示词、上游原文或签名 URL。图片下载改为无鉴权客户端，供应商密钥不发送到图片域名。

## 验证与后续

- 离线角色错误链路、失败不写库、配置原子校验、2.6 官方协议、自定义模型/路径、V2 回归及视频自定义路径通过。
- 相关后端聚焦集合 39 passed；Ruff、Mypy（52 文件）、前端构建通过；Playwright 控制台 3 passed，全部拦截请求。
- 全量后端在新增视频路径参数化前为 264 passed / 11 failed / 1 skipped；随后新增视频路径用例在聚焦集合通过。11 项均为此前级联/Script 契约失败，日志 `.scratch/character-image-503/backend-regression.txt`。
- 没有真实生成、额度查询、图片/视频下载测试；HTTP 测试中的图片是本地内存生成的 PNG。
- 下一步：用户自行填写并启用所选模型密钥；加密持久化、Worker 同步与配置版本仍待完成；真实最小验收需控制预算，不能自动重试旧作业。其他 API 格式需按用户所选模型文档新增 Adapter。

官方依据：[万相 2.6 图像 API](https://help.aliyun.com/zh/model-studio/wan-image-generation-api-reference)。相关任务：`.scratch/character-image-503/`。

## 本地部署结果

仅执行 `docker compose build api` / `docker compose up -d --no-deps api`，未重启 Worker/beat、未重试历史作业。API 健康正常，5173 代理可读取新增字段，OpenAPI 已包含 imageProtocol。

已提前向用户说明重启的内存配置限制。根据 `.scratch/character-image-503/pre-deploy-masked-config.json` 保留测试/正式模型及非密钥参数。当前文本为 production / qwen-plus，图片为 test / wan2.6-image，视频为 test / wan2.7-i2v。测试套密钥无法从掩码恢复，因此图片/视频 test 保留选中但 disabled / configured=false，等待用户自行填写密钥并勾选启用；没有套用正式套密钥，也没有切换用户模型。正式套使用环境初始化的密钥，非密钥配置已恢复。

用户视频测试配置原有 480P 已原样保留。当前适配器对 wan2.7-i2v 的 480P 返回 VIDEO_RESOLUTION_INVALID；用户需要按供应商规格改为 720P/1080P。没有替用户自动提高分辨率或触发计费验证。
