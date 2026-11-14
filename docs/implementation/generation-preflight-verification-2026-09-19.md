# 02生成准备单与12B画面页验证记录

日期：2026-09-19。用户授权继续下一步本地功能。02与12B限定范围完成；03持久作业、04恢复界面和其余UI仍未完成。

## 实现与使用

进入「画面」后，右侧自动读取「生成准备单」，此操作不调用文本/图片/视频生成模型。核对模型、配置版本、分辨率、时长、画幅、风格、引用顺序、动作及准确台词后，才可点「生成当前镜头」。准备请求失败或缺条件时禁用生成；生成报错后须主动刷新准备单再检查，不自动重试。切镜头时只读描述和准备信息同步切换，不残留上一镜头输入。

准备单显示的是当前生效配置，H3使用Provider配置的768P/1080P/2K，不读取镜头中残留的2K字段。已有资产的模型/记录时长独立显示，不用新配置冒充历史产物。删除固定1080×1920/30fps、空参数按钮及无资产播放按钮，未检测的媒体尺寸/帧率如实说明。

「生成全部」仍是可能计费的显式动作；逐镜头准备→提交，失败即停止。第二镜头的上一尾帧是否存在，要等第一镜头生成及抽帧完成后才能判定，不把整批事先伪报通过。

## 共享契约

- POST `/api/projects/{projectId}/shots/{shotId}/visual/preflight`，输入`expectedVersion`。沿用项目访问权限，不写项目/作业/资产。返回`ready`、`fingerprint`、实际参数、参考清单、提示词、调用次数、校验错误和警告。
- POST同路径的`visual`可携带`preflightFingerprint`；提交先重新组装和校验，再比较指纹。旧准备单返回409 `PREFLIGHT_STALE`，尚未调用生成模型。版本冲突仍返回既有409。
- 为兼容原API消费者和自动会话，指纹字段可省略；省略代表服务端即时准备后提交，不表示跳过校验。前端单镜头携带所查看的指纹，批量为每个镜头新建准备单；局部重生成、自动会话及Worker推进最终都走`generate_shot_visual`的共享门禁。
- Pipeline抽出`_prepare_shot_visual`作为唯一组装入口，保留已有连续性策略；`production/visual_preflight.py`负责安全输出、素材存在性检查与指纹。H3/Wan的`prepare_preview`复用实际`reference_plan`/请求编译器；内置Mock明确标识模拟。未知Adapter返回`VIDEO_PREFLIGHT_UNSUPPORTED`阻断，不能跳过准备门禁。
- 指纹包含镜头/风格快照、角色设定与revision、角色板来源信息、现有视频/尾帧有效性、配置revision和Adapter配置身份、实际提示词或扩写规则。配置凭据只作为内部摘要输入，不输出。存在对象键的签名URL续期不改变指纹；外部URL变更会改变指纹。
- 参考清单只返回标签、用途、名称、来源摘要和文件状态，不返回对象键、签名链接或Base64。提示词/台词内若粘贴链接也会隐藏，界面明确这一点。参考整板仍优先于同角色主图/三个视角；尾帧普通参考与严格首帧明确区分。
- 新资产记录`preflightFingerprint`与`requestedParameters`。它们是提交输入记录，不是实测媒体规格，也不是持久生成作业。

## 提示词与成本披露

Context-IR：调用原有本地中文编译器，准备单可显示提交文本；预计0次文本生成、1次视频生成。平台内部优化结果不可见，不声称执行英文H3 Skill。

local-skill：`H3SkillPromptWriter.prepare_input`与`write`共用同一系统规则、引用清单及预算。准备单显示扩写输入、实际Skill/系统规则和文本模型，不把输入称作最终英文提示词；预计1次文本扩写、1次视频生成。最终扩写仍在提交中做长度/对白/引用等校验；失败可能仅消耗文本额度。Skill文件缺失和本地预算问题提前阻断。

Wan：预览复用真实请求编译，展示实际`size`/`resolution`/时长/画幅和首帧用途；本地拼接提示词，`prompt_extend=false`。费用没有报价依据时显示未知，不推断免费额度。调用数不包含供应商查询和媒体下载。

## 验证结果

先RED：新增3项测试，准备端点404/方法不存在；实现后扩展为15项准备契约测试。

| 检查 | 最终结果 |
| --- | --- |
| 禁网后端全量 | 699 passed，3 skipped |
| Ruff（backend/src、backend/tests） | 通过 |
| Mypy（backend/src/comicflow） | 72个源文件通过 |
| 前端TypeScript/Vite build | 通过 |
| Node前端逻辑 | 27 passed |
| Playwright全量 | 62 passed |
| 桌面/390px | 准备单可读、可滚动，无水平溢出；无空播放按钮 |

后端覆盖：预览不写入、不调用模型；Context-IR预览与MockTransport捕获的提交文本/参数相同；Skill扩写输入与实际writer相同；规则、角色revision、注册模型/分辨率变更使旧准备失效；签名续期不失效；人物板→尾帧→场景顺序；引用超限/混用/过长/内网裸链接/文件缺失阻断；权限和项目版本；Wan实际参数；未知Adapter、局部重生成及Worker调用的自动会话不能绕过门禁。

浏览器新增2项：查看/刷新/失败/旧准备单/切镜头/窄屏；批量第二镜头缺尾帧时不提交。已有导航测试允许新增只读POST准备请求，仍断言没有生成；旧测试假视频Provider继承Mock预览能力，H3组装夹具补有效动作和明确context-ir，不取消生产校验。Node测试加载器支持新错误消息模块，仍测试真实client函数与原失败断言。

全量后端隔离环境并拦截socket连接；3个跳过为2个未提供本地H3样本和1个需显式开启的Docker基础设施测试。既有Starlette/httpx弃用警告不影响通过。浏览器业务请求使用fixture；代理指向`127.0.0.1:9`，辅助请求未拦截时连接拒绝，不接本机真实API。首次并行构建曾让旧边界扫描测试遇到正在替换的dist文件，最终先构建后跑后端，已通过。

主要命令：

```powershell
.venv/Scripts/python.exe var/verification/generation-preflight-20260919/run_offline.py
.venv/Scripts/python.exe -m ruff check backend/src backend/tests
.venv/Scripts/python.exe -m mypy backend/src/comicflow
$env:VITE_API_PROXY_TARGET='http://127.0.0.1:9'
pnpm --dir frontend build
node --test frontend/tests/*.test.mjs
pnpm --dir frontend exec playwright test
```

使用本机已有FFmpeg加入测试进程PATH。日志/禁网runner/截图保存在忽略目录`var/verification/generation-preflight-20260919/`。不把日志中的历史失败当成最终结果，也不把模拟通过等同真实画质通过。

## 边界与下一步

- 预览对实际选中的存储图片做exists检查；测试替身不支持exists时标记未核验。图像字节的尺寸/格式/总大小继续由现有Adapter在付费前验证，远程图片URL不在准备阶段主动下载。文件存在不代表图片有效，UI已提示。
- 不更改H3后续镜头参考模式：有角色参考时上一尾帧通常作为普通参考，不能承诺像素级首尾无缝；连续性策略调整属于05。只修正严格首帧分支遗漏移除角色板字段的冲突风险。
- 指纹不是锁，不解决请求超时后的任务恢复、多个进程同时生成或幂等结算；当前供应商幂等键仍沿用项目/镜头/版本。03应将准备快照绑定持久作业和提交状态，谨慎处理模型/角色变化但项目版本不变时的幂等身份，不因换指纹自动重发未知任务。
- 页面仅展示脱敏素材清单；逐张图片预览/更丰富素材详情留给后续工作区/资源集成。未做全站UI改版、一次调用整板或旧项目换风格。
- 下一步03+04A：先持久保存准备快照、供应商任务号/阶段/错误，再提供刷新或超时后查询已有任务的入口；未知提交禁止自动重提。

回溯副本在`var/change-backups/generation-preflight-20260919/manifest.json`；保留当前其他未提交改动，不全量reset/clean。其中reference_reanchor测试副本依据本轮精确编辑逆向恢复了两个fixture字段，其余为改前复制。新增文件可从本记录和diff识别。本轮真实模型调用0，未提交/推送/部署、迁移数据或启动Worker/Beat。
