# API 测试与正式配置切换

> 后续增量：模型名称完全由用户填写，切换供应商保留模型和地址；新增图片协议与图片/万相视频自定义路径，wan2.6-image 使用正确异步 messages 协议。角色图片 503 排查与最新配置方法见 `model-protocol-configuration.md`。

日期：2026-09-09。用户要求图片、视频等 API 可通用配置并方便测试/生产切换。实现范围为文本、图片、视频三种能力；不是任意供应商协议自动兼容。

## 使用方式

打开右上角“模型 API”，每种能力都包含：

1. **当前状态**：显示正在使用的测试/正式配置与模型；关闭能力时显示未启用。
2. **编辑配置**：选择测试或正式，只切换编辑对象，不改变实际 Provider。
3. **保存配置**：非当前套保存后不切换；修改当前套保存后立即生效。
4. **切换使用测试/正式配置**：使用已保存的另一套配置，不需要再次填写密钥。
5. **清除本套配置**：保留另一套；清除当前文本/视频套切回显式 Mock，清除当前图片套停用参考图生成。

两套密钥独立。留空只复用本套密钥；更换协议、服务域名或 HTTP/HTTPS 协议时要求新密钥，避免将优云密钥传给百炼。密钥不进入浏览器存储，不通过读取接口回传。

测试套是用途名称，不是免费模式。百炼免费额度由供应商账户控制，请先核实北京地域剩余额度、有效期，并提前开启“免费额度用完即停”。保存、切换本身没有模型调用。

## 建议配置

| 能力 | 测试套 | 正式套示例 |
| --- | --- | --- |
| 文本 | 已开通且有额度的兼容文本模型，如 qwen-plus | 单独的文本模型/密钥 |
| 图片 | 百炼 `wan2.2-t2i-flash`，720*1280，每次 1 张 | 当前 `wanx2.1-t2i-plus`，或已核验的同协议模型 |
| 视频 | 百炼 `wan2.2-i2v-flash`，图生视频，480P，剧本镜头 5 秒 | 优云 MiniMax H3，保留现有模型与路径 |

测试套第一次需要填写对应平台密钥并保存启用，再点击“切换使用测试配置”。正式套从服务器现有环境配置初始化。不会自动切换模型或发起生成以探测额度。

图片协议：百炼万相异步文生图。视频协议：百炼万相图生/文生视频和优云 H3。文本：当前 Chat Completions + JSON 输出兼容协议。语音、口型、合成仍只读显示实际运行时，由环境配置；其他协议需独立 Adapter 后再加入选项。

模型下拉候选只是填写建议，也可以输入同协议模型 ID；云端账号权限与未知模型参数仍需按官方文档核对。没有宣称任意名称可调用。

## 百炼视频与流水线接入

修正 `bailian_i2v.py` 原型，现实现主链路的 `generate(shot, characters)`：

- 通过 `/services/aigc/video-generation/video-synthesis` 异步提交，设置 `X-DashScope-Async: enable`。
- 图生视频用 `input.img_url` 和 `parameters.resolution`；轮询 `/tasks/{task_id}`，成功后下载视频并写入对象存储。
- 文生视频不发送首帧：2.7 模型使用 resolution/ratio，早期协议使用 size；界面必须选对应 t2v 模型。
- 结果包含 `mediaType=video`、供应商、模型、请求引用、时长、分辨率、对象键，进入已有尾帧提取、合成流程；无自动重复提交。
- 下载视频使用独立无鉴权客户端，供应商密钥不发送至资产域名。
- 捕获镜头开始时的 Provider 实例，避免异步执行期间切换配置影响同一次供应商提交。

图生视频首帧优先：显式首帧 → 当前镜头已保存图片 → 场景内上一镜头有效尾帧；场景首镜头无人物时可用场景背景，单角色时可用该角色参考图作动作测试。多角色无完整关键帧时拒绝生成，不自动花费图片额度补图，也不以空背景假装融合了人物。

H3 的多参考/首尾帧模式与万相基础图生视频不同，显式不兼容模式会被拒绝。万相使用镜头中文画面、动作、情绪、运镜、风格和角色文字约束，`prompt_extend=false`，不额外调用文本 API。H3 继续每次执行 `h3-prompt-writing`，不因切换配置而取消 Skill。

时长沿用保存的剧本，不能自动把 10 秒改成 5 秒导致声音/时间轴错位。`wan2.2-i2v-flash` 固定 5 秒，`wanx2.1-i2v-turbo` 支持 3/4/5 秒；输入不合格在请求前返回中文错误。未知模型规则和真实质量未验收。

## 接口与存储范围

```text
GET /api/provider-config
  profiles.{text|image|video}.{active|test|production}
PUT /api/provider-config/profiles/{capability}/{test|production}
POST /api/provider-config/profiles/{capability}/{test|production}/activate
DELETE /api/provider-config/profiles/{capability}/{test|production}
```

旧文本/媒体配置接口继续操作当前套配置。非法输入、协议冲突、密钥缺失时先拒绝，原配置和当前 Adapter 保持不变。

**当前仍是 API 进程内配置**：API 重启后页面保存的套配置不保留，重新读取 `.env`；Worker 不读取页面切换。配置页常驻提示该范围。双配置切换可用于本地 API 交互验证，但还不能当成长期生产的共享配置中心。

下一阶段需要加密持久化、配置版本、管理员权限和 API/Worker 共享读取；作业固定配置版本、定义进行中作业对轮换/删除的处理。不能把“正式配置”标签当作生产验收结论。

## 离线验证与交接

- 新增 `test_provider_profiles.py`：三种能力保存/切换/清除、密钥隔离/掩码、非法配置原子拒绝、H3 切回后绑定当前文本模型。
- 新增 `test_bailian_video.py`：正式协议形状、单次提交、HTTP 错误、下载不带密钥、对象存储、无效模式/时长/首帧拦截、2.7 文生视频参数、镜头图片与单角色首帧选择。
- 新增用例最终 17 passed；相关聚焦集合 45 passed。Ruff、Mypy（53 文件）、前端构建通过。
- Playwright 控制台/角色/剧本预览共 7 passed；修正控制台布局后单独重跑控制台 2 passed，全部拦截请求。
- 全量后端 **255 passed / 11 failed / 1 skipped**；11 项同名旧级联/Script 契约失败仍保留。日志 `.scratch/provider-profile-switching/backend-regression.txt`。
- 本轮没有真实文本/图片/视频请求，没有额度查询；不替用户点击免费额度控制开关。

## 本地部署记录

已执行 `docker compose build api` 与 `docker compose up -d --no-deps api`，仅更新 API，未重启 Worker/beat，未重触发历史作业。`http://127.0.0.1:18001/health` 返回 ok；通过前端 5173 代理读取配置成功，三种能力的 active 均为 production，测试套尚未配置。

重启后密钥来自 `.env`。根据 `.scratch/provider-profile-switching/pre-deploy-masked-config.json` 恢复原图片启用状态和非密钥参数，保存时省略密钥以使用本套环境初始化密钥；读回图片 `BailianImageProvider`、模型 `wanx2.1-t2i-plus`，视频 `MinimaxH3Provider`。该快照只有掩码，无法恢复用户可能只保存在旧进程中的不同密钥。服务健康与配置读回不等于供应商鉴权、额度或真实生成已验收。

相关调研：[模型建议](../research/bailian-image-video-model-recommendation.md)、[免费额度](../research/bailian-free-quota-notes.md)。

官方依据：[文生图](https://help.aliyun.com/zh/model-studio/text-to-image-v2-api-reference)、[图生视频](https://help.aliyun.com/zh/model-studio/image-to-video-api-reference)、[2.7 文生视频及迁移差异](https://help.aliyun.com/zh/model-studio/text-to-video-api-reference)、[免费额度规则](https://help.aliyun.com/zh/model-studio/new-free-quota)。
