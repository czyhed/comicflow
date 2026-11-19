# ComicFlow 阻塞点追踪

**最近更新：** 2026-09-07
**验证环境：** Docker 真实栈（API 宿主 18000），`PROVIDER_MODE=real` /
`VISUAL_PROVIDER_MODE=real` / `TTS_PROVIDER_MODE=real`

---

## 🔴 当前阻塞（浏览器实点新发现）

### 5. 前端故事生成完成后不前进——UI 停在「准备扩写故事…」
**现象：** 浏览器实点 `automatic` / 60 秒，点「生成故事文本」后：
- 后端 **22 秒内正常完成**：`stage=story-generated`、`generatedStoryText` 273 字、
  `generationError=null`（`var/acceptance/snapshot.json` 为实测快照）
- 前端右侧一直显示「准备扩写故事…」，按钮停在「正在生成…」，**永不出现进入剧本的入口**
- 无 5xx、无 console error——**静默卡死，不是报错**

**根因（已修正——早期诊断有误，见文末更正）：**
渲染分支 `CreateWorkspace.tsx:298` 的条件是 `storyText && !generatedScript && activeMode === 'automatic'`，
而 `:166` 是 `const activeMode = mode`——`mode` 是**用户在界面上选的模式**（`:33` 的
`useState`），不是项目**已保存**的模式。

`:148-152` 有个 effect 本该用 `snapshot.project.input.mode` 回填 `mode`，但守卫是
`if (generate.isPending || generate.data) return`——生成成功后 `generate.data` 恒有值，
**这个回填永久不执行**。

**修复注意：** `mode`、`storyText`、`draftScript` 三处状态都由「UI 选择」和「项目已存」
两个来源竞争，且各自同步 effect 的守卫条件都不一样。别只改 `activeMode` 一处就当修好——
要确认**刷新浏览器后状态能恢复**（验收计划阶段 1 完成标准之一）。

**为什么之前没发现：** 上一轮批量生成用自写脚本按顺序调 API，**跳过了 UI 状态机**；
`frontend/tests/e2e/*.spec.ts` 全部 `page.route` mock 掉后端，也从未跑过这条真实路径。
这正是「浏览器实点」必须补的原因——它是 3 个已验步骤之后的第一个真实用户动作。

**影响范围：** `automatic` 模式**完全走不下去**。用户点完生成就卡住，只能刷新页面。
（`import_story` 模式跳过故事生成，所以上一轮没撞上。）

**验收状态：** 60 秒 / 10 镜头验收**在第一步即受阻**，未能进入拆分/生成/导出。

> ⚠️ **更正：** 提交 `2fe2ef2` 的信息里写的根因（"`onSuccess` 用 `setSnapshot` 写本地
> state，状态行读 `project?.stage`"）**是错的**——代码里没有 `setSnapshot`，`onSuccess`
> （`:122`）确实写了 `setStoryText`，也确实调了 `invalidateQueries`（`:132`）。
> 以本节上方的诊断为准，不要照那条提交信息去改。


---

## ✅ 已修复的阻塞问题

### 1. 导出包"只有文字"——合成缺前置资产校验
**现象：** 10 镜头项目只生成了 1 张画面，导出照样成功，产出的 MP4 几乎全是文字卡。
**根因：** `request_composition` 不校验资产覆盖率，直接建合成 job；FFmpeg 对缺画面的
镜头用文字卡兜底，把失败藏进了交付物。
**影响范围：** 所有部分生成的项目——即最常见的中断/重试场景。
**修复：** `pipeline.py` 新增 `_composition_readiness()` + 入口门禁，不满足抛
`ASSETS_INCOMPLETE`（409）并透出缺失镜头清单。口径：每镜头必须有 `valid` 画面；
仅有台词的镜头才要求配音。
**回归：** `backend/tests/test_composition_readiness.py`（6 例）
**决策记录：** `docs/DECISION_LOG.md` 2026-09-07 合成前置资产完整性门禁

### 2. 拆分剧本间歇性 502
**现象：** 同样的输入，有时成功有时 502 `PROVIDER_INVALID_RESPONSE`。曾误判为与时长相关。
**根因：** `normalize_preview` 要求 `dialogue` 和 `narration` **都**是 `str`；模型省略
未使用的那个键时取到 `None`，`isinstance(None, str)` 为 False，**合规剧本被整份拒绝**。
触发取决于模型当次是否省略可选键，故表现为间歇。
**影响范围：** 所有剧本拆分请求。
**修复：** 校验语义改为"至少一个非空台词"，缺失键补 `""`；类型错误仍拒绝。
**回归：** `backend/tests/test_script_preview_lines.py`（4 例）
**残留：** 场景五字段（`time`/`location`/`narrativeGoal`/`conflict`/`turningPoint`）
仍按存在性+非空校验，**同类缺陷未修**——502 只治了个例没治类。

### 3. 前端把用户领到死胡同 / 看不懂拒绝原因
**现象：** 几乎空的项目也能点到导出；后端拒绝后只显示裸错误码；音频页空状态无生成入口。
**根因：** `client.ts` 的 `request()` 丢弃错误响应体；就绪判断在各 workspace 各写一遍；
`AudioWorkspace` 空状态缺出口。
**修复：** 新增 `ApiError`（保留 detail）、`production-readiness.ts`（就绪判断单一来源，
与后端同口径）、`use-batch-generation.ts`（逐镜头串行，`projectVersion` 链式传递）；
重写 Export/Visual/Audio 三个 workspace。
**顺带清除：** `VisualWorkspace` 写死的"一致性 96%"等**未经测量的造假指标**——展示未测量
的数字比不展示更有害。

### 4. 连通性测试端点对健康环境谎报 503
**现象：** `POST /api/provider-config/text/test` 返回 503 `PROVIDER_UNAVAILABLE`，而容器内直连
百炼两次均 HTTP 200——密钥和网络都正常。
**根因（两个缺陷叠加）：**
1. 端点用 `generate_script()` 探连通性，会跑**完整业务校验**；提示词只要"最小 JSON"，模型照做
   返回 `{"title":"","scenes":[],"shots":[]}`，语法合法但内容空，必然违约。
2. 由此得到的 `PROVIDER_INVALID_RESPONSE` 不在端点内联映射表里，落到 `PROVIDER_UNAVAILABLE`
   兜底。同一张表有**三份副本且已漂移**，`pipeline.py` 剧本生成路径缺同一项。
**影响范围：** 验收第一道门（`ACCEPTANCE_PLAN.md` 0.5 / `TASK_PLAN.md` 0.2）。失败方式会把人
引向查密钥、查网络——完全错误的方向。**该端点在真实环境下永远返回 503。**
**修复：** 新增 `check_connectivity()`（1 token、无内容校验、返回实际应答模型、401/403 归
`PROVIDER_AUTH_FAILED`）；新增 `providers/error_mapping.py` 作为唯一映射表，三处调用点统一。
**回归：** `test_text_provider_connectivity.py`（8）+ `test_provider_error_mapping.py`（8）
+ `test_provider_config_endpoint.py`（6）。该端点此前**零覆盖**，这是缺陷能存活的直接原因。
**反向验证：** 已分别重新注入两个缺陷并确认测试失败（含复现"健康 provider 得 503"），再恢复。
**实测：** `200 {"ok":true,"model":"qwen-plus"}`

---

## ✅ 已验证可用（真实栈实测）

- [x] API 健康检查 `/health`（18000）
- [x] 百炼文本连接（qwen-plus，端点修复后）
- [x] 创建项目（`import_story` 模式）
- [x] 拆分剧本（修复后不再 502）
- [x] 确认剧本（版本号校验）
- [x] 生成视觉资产（wanx2.1-t2i-plus，抽三帧确认为真实画面）
- [x] TTS 生成（qwen3-tts-flash）
- [x] 批量生成 6 镜头（约 2 分钟，串行）
- [x] 合成门禁：零资产 → 409 + 缺失清单
- [x] FFmpeg 合成：资产齐全 → 202 → `succeeded`
- [x] 导出产物：MP4 1080×1920 / H.264+AAC / 30.0s / 4.5MB

**门禁：** 后端 `pytest` 181 passed 1 skipped（基线 150）；`ruff`（CI 范围
`backend/src backend/tests`）+ `mypy` 通过；前端 `tsc -b` + `vite build` 通过。

---

## ❌ 尚未验证（不要当作已通过）

- [ ] **浏览器实点批量生成** —— 已尝试，**受阻于上方问题 5**（卡在故事生成，进不到批量生成）
- [ ] **`automatic` 模式端到端** —— 已尝试，**受阻于上方问题 5**
- [ ] **60 秒 / 10 镜头** —— 原始失败形状；只测了 30 秒 / 6 镜头
- [ ] **E2E**：`pnpm --dir frontend test:e2e` —— 另注：Playwright **test runner 在本机挂死**
      （连不开浏览器的空测试都超时零输出），但 `playwright screenshot` 与 `playwright-core`
      直接驱动均正常。验收改用 `var/drive-acceptance.mjs` 绕开 runner。runner 本身待查。
- [ ] **重复性**：暂定先跑 1 次（见 `docs/DECISION_LOG.md`），受阻于问题 5

---

## 🔧 非阻塞待办

- [ ] **Provider 状态不可见，且首页有会误导人的假控件** —— 两处：
      ① `AppShell.tsx:63` 在 `snapshot` 为空时显示「Mock 创作环境」，与真实 Provider 无关，
      纯占位文案，但首页必然显示它；
      ② `CreateWorkspace.tsx:39` 的模型下拉默认选中「Mock Story Director」，而 `model` 状态
      **只被读写自身、从不发给后端**——真实 Provider 由后端 `.env` 决定。这是个**纯装饰控件**，
      却让人以为自己在用 Mock。比"看不见状态"更糟：它显示了错误的状态。
      页面应改为显示后端真实能力（文本:真实 / 画面:真实 / 声音:真实）。
- [ ] **契约健壮性** —— `normalize_preview` 场景五字段同类缺陷（见上文残留）
- [ ] **画质三问题**（均在 `bailian_visual.py:_build_prompt` 一处）：
      风格从动漫跳到写实（需统一 `style_hint`）；人物不连贯（需内联角色外观——注意
      `characterIds` 契约里有但 pipeline/provider **完全没用**）；画面内文字乱码
      （如 "AOT SONT AOT"，需在提示词中禁止画面内文字）
- [ ] **BGM / 音效完全缺失** —— PRD 标为 P0
- [ ] **wan 文生视频未接流水线** —— `BailianVideoProvider` 已存在
- [ ] **`ProductionPipeline` 1812 行单文件** —— 已登记，等流程稳定后再议

---

## 📝 测试记录

### 2026-09-07 —— 浏览器实点 `automatic` / 60 秒（受阻）
**方式：** `var/drive-acceptance.mjs` 用 playwright-core 直接驱动真实 UI（5173→18000），
不 mock 任何 API。绕开挂死的 Playwright test runner。
**结果：** **在第一步受阻。** 首页渲染正常；「全自动生成」确认为默认选中；故事填入成功；
点「生成故事文本」后后端 22 秒完成（`story-generated` / 273 字 / 无错误），
但前端永远停在「准备扩写故事…」。见上方阻塞问题 5。
**顺带发现：** 首页「Mock 创作环境」+「Mock Story Director」两个误导性标签（见非阻塞待办）。
**证据：** `var/acceptance/01-after-story.png`、`var/acceptance/driver.log`、
`var/acceptance/snapshot.json`

### 2026-09-07 —— 三处根因修复验证
**流程：** `import_story` → 拆分 → 确认 → 批量生成 6 镜头 → 导出
**结果：** 通过。零资产请求合成得 409 + 缺失清单；资产齐全 202 →
`succeeded`；产物 MP4 1080×1920 H.264+AAC 30.0s，抽三帧均为真实 wanx 画面。
**耗时：** 批量生成约 2 分钟（6 镜头，串行）
**说明：** 批量生成用自写脚本执行，**未经浏览器**；`automatic` 模式与 60 秒/10 镜头未测。
