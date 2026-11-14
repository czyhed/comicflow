# 多模型控制台：保存一次，按用途切换

状态：2026-09-17 已实现，功能聚焦离线检查通过；本地API/Worker/Beat已更新、数据库已迁移，5173模型库接口返回200。全量仍有既有失败，远端服务器部署暂停。

## 使用方法

1. 打开「模型 API」，进入新的「模型管理」。
2. 在「连接与密钥」添加平台名称、API 基础地址和 Key。一个连接可以被多个模型复用；不同账户/密钥建立不同连接。
3. 在「模型列表」新增模型，选择连接、调用协议，填写准确的 model ID。可复制已有模型，修改名称/ID/参数后保存，不覆盖原模型。
4. 在「用途选择」分别指定故事、剧本拆分、人物提示词、视频提示词润色、文生图、图生图和视频使用哪个模型。可以共用同一个模型。
5. 保存、用途切换、离线预览都不请求模型。启用模型不等于已绑定用途；未绑定用途会明确沿用服务器原配置。

空模型库提供「导入当前 API 配置」，一次导入当前 API 进程里可读的测试/正式双槽及环境初始化配置，包括密钥。
导入不会推断或替换原模型；已丢失的旧进程内存 Key 无法通过掩码还原，需要填写一次。
「查看旧双槽配置」保留旧界面；新模型库已有用途绑定时，旧写接口会拒绝修改，避免双重配置互相覆盖。

## 测试连接

每个「连接与密钥」卡片都有「测试连接」按钮，只测试已保存的配置；修改连接/模型后先保存。

- 文本连接：在下拉框选择此连接下的文本模型，然后点击。使用实际地址、Key、模型ID、参数模板和响应映射，发送一次ping，强制非流式和输出上限1；最多15秒，不重试。供应商可能收取少量文本费用。模型未启用也可检查，不改变用途绑定。
- 图片/视频连接或尚未添加文本模型：可选「仅检查地址可达」。只GET基础地址、不带Key、不跟随跳转、不创建生成任务。收到响应显示HTTP状态和“模型尚未验证”；基础地址404也可能说明域名可达但没有首页，不能证明API路径/Key正确。
- 文本测试显示成功/失败、HTTP状态、可识别的原因和参数名、所测模型、耗时及配置版本；不显示上游原始正文或密钥。并发配置更新需刷新后再测。

文本测试通过只说明最小请求被所选模型接受，不保证完整故事的长度、结构契约或所有生成参数都通过。失败后按显示原因核对，不反复点击故事生成。测试不会自动修正模型ID、地址或模板，不会自动发送第二次请求。

## 高级 JSON

JSON 是所选协议的配置，不是可执行代码。普通用户可以直接使用「填入协议默认参数」。
协议切换会重置 JSON，模型切换不会修改其他模型。

文本/Chat 图片示例：

```json
{
  "timeoutMs": 120000,
  "request": {
    "path": "/chat/completions",
    "body": {
      "model": "{{model}}",
      "messages": "{{messages}}",
      "temperature": 0.7,
      "max_tokens": 4096
    },
    "headers": {"Authorization": "Bearer {{apiKey}}"}
  },
  "responseTextPath": "choices[0].message.content"
}
```

`model` 和 `messages` 必须保留占位符，确保实际使用所选模型、原有 Skill/system 提示词和当前输入。
整个占位符替换保留 JSON 类型，数组不会变成字符串。API Key 只允许从连接注入请求头，不要把真实 Key 写进 JSON。
`path` 是相对于基础地址的路径，例如基础地址 `/api/v3` 加 `/chat/completions`；不允许跨域绝对 URL。
响应路径只接受点号/数字下标，不执行表达式。自定义文本模板采用一次非流式请求，通过现有故事事件返回结果，
不把未知响应格式当成 SSE；`stream=true` 不支持。保存不会验证供应商是否接受 temperature 等业务参数。

### 地址与用途核对

| 协议 | 基础地址示例 | 相对路径 |
| --- | --- | --- |
| 火山方舟Chat | `https://ark.cn-beijing.volces.com/api/v3` | `/chat/completions` |
| Chat图片（本项目既有接口） | 图片平台根地址，如`https://img.yunfei.best` | `/v1/chat/completions` |
| 万相2.6图片/编辑 | `https://dashscope.aliyuncs.com/api/v1` | 默认`/services/aigc/image-generation/generation` |
| 优云H3 | `https://cp.compshare.cn` | 默认`/minimax/v2/video_generation` |

路径按基础地址拼接，不会自动去掉重复的`/v1`。Chat图片平台若要求基础地址带`/v1`，则显式把request.path改为`/chat/completions`；自定义路径始终优先。只填写request.body时保留协议默认路径。离线预览用于核对最终Chat请求地址，不代表供应商已接受请求。

万相图片/视频不能使用百炼文本专用的`/compatible-mode/v1`基础地址。需要同时调用百炼文本和图片时建立两个连接，分别绑定模型；不要为了修图片改掉所有文本模型共用的连接。本项目会在本地拦截已知错误搭配。

人物提示词和剧本拆分可复制同一文本模型，分别设置timeoutMs至300000并独立绑定；不需要更换model ID或重填同一连接的Key。长等待不等于成功，不会增加自动重试。人物提示词失败保留原角色，页面提示对应阶段和安全错误信息。

H3 参数示例：

```json
{
  "timeoutMs": 600000,
  "resolution": "768P",
  "h3PromptMode": "context-ir",
  "submitPath": "/minimax/v2/video_generation",
  "queryPath": "/minimax/v2/query/video_generation/{task_id}"
}
```

H3 参考图、首尾帧、时长、提示词长度和幂等规则仍由既有 Adapter/流水线执行，不能用 JSON 任意覆盖。
768P 保持默认。中文 Context-IR 不额外调用本地视频文本扩写；选择 local-skill 才使用「视频提示词润色」绑定的文本模型。
故事/剧本和图片上游的 Manju/XiaoLuo 规则保持原路径。

## 支持范围

| 协议 | 用途 | 可配置内容 |
| --- | --- | --- |
| Chat Completions / 火山方舟 Chat | 故事、拆分、人物/视频提示词 | 模型ID、连接、超时、请求路径/体/头、响应文本路径 |
| Chat 图片（Markdown Base64） | 文生图 | 同上，供应商必须返回兼容的 Markdown Base64 图片内容 |
| 万相 V2 | 文生图 | 模型、尺寸、超时、提交/查询路径 |
| 万相 2.6 | 文生图、图生图/三视图 | 模型、尺寸、超时、提交/查询路径 |
| 优云 H3 | 视频 | 模型、分辨率、提示词模式、超时、提交/查询路径 |
| 万相视频 | 视频 | 模型、t2v/i2v、分辨率、超时、提交/查询路径 |

模型名称可自由填写，不自动证明其支持某种能力。`image-2.5` 是否支持图生图，要由其平台实际协议决定，
不能在控制台简单勾选后就获得支持。Responses、标准 Images/multipart、新语音协议、任意私有异步协议本轮未实现。
图片/视频的「离线预览」明确标为适配器参数，不伪装成带真实参考图的最终请求。

## 存储和版本

- 正式运行时使用 PostgreSQL `model_registry_versions`；内存测试运行时界面明确提示重启不保存。
- 每次修改是不可变新版本，乐观锁阻止不同窗口覆盖。引用中的模型/连接不能直接删除，已绑定模型不能直接禁用。
- API 每个请求读取一个版本并独立构造 Provider，不修改其他请求的 Provider。Worker 读取同一数据库；
  排队的合成作业和新生产推进事件携带版本号，已有事件缺少版本号时保留兼容处理。
- 已开始的视频提交、轮询和下载使用同一个 Provider 实例，切换默认模型不影响该次调用。
  已生成视频资产记录 `modelConfigRevision`。旧手动恢复脚本尚不提供模型库选版本参数；恢复历史任务前需核对原连接，不能重新提交。
- 连接 Key 使用 Fernet 加密。主密钥来自 `MODEL_CONFIG_ENCRYPTION_KEY`，或首次保存时自动生成到
  `MODEL_CONFIG_KEY_FILE`（默认 `var/config/model-config.key`）。密钥文件原子创建，不能覆盖已有密钥。
  若数据库已有密文但原主密钥丢失，新保存会明确失败，不会生成另一把密钥掩盖问题。
- Docker 为 API/Worker/Beat 共享独立配置密钥卷。备份数据库时须另行妥善备份主密钥；不要提交到 Git。
  主密钥丢失将无法解密旧配置；本轮不实现自动密钥轮换。

## 启用新代码

远端部署仍暂停，没有替用户试生成。为修复前端已更新而本地后端旧镜像导致的模型库404，已备份并升级本机数据库、更新API/Worker/Beat；原项目内容与旧模型配置核对未变。
其他环境启用时，应先安装新依赖、执行 Alembic 升级，再使用同一版本重启 API/Worker/Beat，最后构建前端。
独立 Python 环境在确认目标数据库后执行：

```powershell
uv sync --frozen
uv run --env-file .env alembic upgrade head
pnpm --dir frontend build
```

Compose 已配置共享密钥卷；生产 Drone 仍先迁移再更新服务。不要执行 `down -v`，也不要删除配置密钥卷。
独立分仓需要重新导出并上传相应新源码才会生效，本轮未推送到 GitHub、Gitee main 或触发部署。

## 验证记录

新增后端 29 项通过；相关页面 9 项通过，布局修正后新页面 2 项再次通过；Node 18 项、前端构建、Mypy、新模块 Ruff、开发/生产 Compose 解析和隔离 SQLite 迁移升降级通过。
最终后端全量 573 passed、14 failed、3 skipped。既有失败涉及百炼参考协议、Mock 级联/合成、剧本和提示词契约、运行时配置及本机 Redis 未启动；没有跳过门禁或宣称全项目通过。
本轮未调用真实模型。后续本地启用已完成PostgreSQL迁移及API/Worker/Beat源码与共享配置卷检查；5173和18001真实HTTP均通过。尚未写入目录配置，用户可导入原配置；真实供应商兼容性、远端生产部署和生成画质尚未验收。

## 回退点

Gitee 标签：`backup-before-model-registry-20260917-101221`。
提交：`552050dd38e31cab2a3de63e660df3352da5319d`。

先保存当前工作，另建 worktree 查看旧版本，避免 reset --hard 覆盖工作区：

```powershell
git fetch origin --tags
git worktree add ../comicflow-before-model-console backup-before-model-registry-20260917-101221
```

新增表不修改原项目表，回退应用代码可保留新表；不要为回退而删除配置表或密钥。
