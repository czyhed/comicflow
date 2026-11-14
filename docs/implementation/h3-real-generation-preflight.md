# MiniMax H3 真实视频生成前置审查

状态：代码补全并部署 API，等待 Claude 审查后进行真实 H3 验证

日期：2026-09-12

这份文档用于真实调用前的代码与运行数据审查。目标是先用最少的额度验证 H3 的 Skill 扩写、参考图输入和同场景首尾帧级联，再决定是否继续生成完整 30 秒漫剧。审查完成前不点击“生成全部”，不重复生成已有镜头。

角色参考图输入补充：场景首镜头会将每个角色的正式主参考图及已确认三视图（正面、三分之四侧面、侧面）加入 H3 reference manifest；双角色加场景背景时总数最多 9 张。三视图按固定顺序生成 `<Picture N>` 标签，图片在文本扩写前按对象键从 MinIO 读取并校验。后续镜头使用尾帧级联时会移除全部角色和场景参考图片，只保留前镜头尾帧。

## 一、当前实现结论

H3 生成路径是：

```text
项目已确认剧本
  → 读取角色文字设定和已保存参考图
  → 本地读取并校验参考图片
  → 当前文本 Provider 读取 skills/h3-prompt-writing/SKILL.md 及对应指南
  → 文本 Provider 扩写结构化 H3 Prompt
  → 本地校验时长、章节、语言、角色标签、图片引用和对白
  → 提交 MiniMax H3
  → 轮询已有任务
  → 下载视频并写入对象存储
  → FFmpeg 提取首帧和尾帧
```

每次 H3 生成都必须经过 `H3SkillPromptWriter`。保存过的 `h3Prompt` 不能绕过 Skill，也不会因为已有提示词而跳过文本扩写。

### 场景首镜头

同一场景的第一个镜头可以使用：

- `ref2va`；
- 角色参考图；
- 场景背景参考图；
- 角色文字设定和镜头动作描述。

### 同场景后续镜头

同一场景存在前镜头时，流水线现在固定执行：

- 从前镜头的有效视频资产读取 `lastFrameObjectKey`；
- 将它作为当前镜头的 `firstFrameObjectKey` 和 `firstFrameUrl`；
- 将当前镜头的模式改为 `i2va`；
- 保留角色文字设定供 Skill 编写描述；
- 移除角色参考图和场景参考图，遵守 H3 首帧输入与参考图输入的互斥约束。

前镜头没有有效尾帧时，流水线在文本扩写之前返回 `CASCADE_FRAME_MISSING`，因此不会产生新的文本或视频供应商请求。

切换到新场景后重新开始。新场景的第一个镜头使用该场景自己的参考图，不能把上一场景尾帧跨场景传递。

## 二、已完成的零额度验证

新增测试文件：`backend/tests/test_h3_cascade.py`

测试覆盖：

1. 第二镜头原本被错误设置为 `ref2va` 的缺陷，已经验证修复为 `i2va`。
2. 第二镜头已经收到前镜头尾帧对象键。
3. 后续镜头不会把角色参考图片继续传给 H3。
4. 前镜头尾帧缺失时，供应商 Adapter 不会被调用。

最近一次离线结果：

```text
uv run pytest backend/tests/test_h3_cascade.py backend/tests/test_h3_offline_flow.py backend/tests/test_h3_preflight.py backend/tests/test_h3_validation.py backend/tests/test_h3_response_errors.py backend/tests/test_minimax_h3.py -q
40 passed, 1 skipped

uv run ruff check backend/src/comicflow/production/pipeline.py backend/tests/test_h3_cascade.py
All checks passed

uv run mypy backend/src/comicflow/production/pipeline.py
Success: no issues found
```

`test_h3_offline_flow.py` 的 `current-project` 案例因未设置脱敏副本环境变量而跳过；标准离线样例已执行。离线测试使用 `MockTransport` 和本地 FFmpeg，不代表真实供应商已经验收。

## 三、Claude 必须审查的代码点

请逐项检查并在审查结果中标记 `PASS`、`FAIL` 或 `NEEDS-EVIDENCE`：

### A. 首尾帧级联

- [ ] `backend/src/comicflow/production/pipeline.py` 在 H3 同场景后续镜头中先寻找前镜头，再决定参考模式。
- [ ] 前镜头必须属于同一 `sceneId` / `scene.shotIds` 序列。
- [ ] 前镜头必须有 `valid=true` 的视频资产和 `lastFrameObjectKey`。
- [ ] 尾帧缺失时，错误发生在调用文本 Provider 和视频 Provider 之前。
- [ ] 发送给 H3 的后续镜头模式为 `i2va`，且 `firstFrameObjectKey` 指向前镜头尾帧。
- [ ] 后续镜头不同时携带 `firstFrame*` 与角色或场景参考图片。
- [ ] 新场景首镜头不会使用前一场景的尾帧。

### B. Skill 扩写与校验

- [ ] `backend/src/comicflow/providers/minimax_h3.py` 没有允许保存的 Prompt 绕过 `H3SkillPromptWriter`。
- [ ] `skills/h3-prompt-writing/SKILL.md`、`references/base-en.txt` 和 `references/ref-en.txt` 按模式读取。
- [ ] H3 供应商提交前已经完成结构、时长、章节、语言、引用和台词校验。
- [ ] 台词来自项目保存的 `dialogue` / `narration`，并由应用逐字注入。
- [ ] Skill 扩写失败时不会自动重试或继续提交视频。

### C. 参考图片

- [ ] 首镜头使用的角色图和场景图来自对象存储中可读取的对象键。
- [ ] 图片在文本扩写前完成格式、尺寸、比例和大小检查。
- [ ] 图片 Base64 和签名 URL 不会进入文本 Provider 的上下文。
- [ ] 发送给 H3 的图片 URL 不携带 API 鉴权头。
- [ ] 后续镜头使用尾帧时不会重新用角色图覆盖首帧。
- [ ] 场景首镜头的 H3 manifest 包含每个角色的主图、正面、三分之四侧面和侧面，并且双角色加场景图不超过 9 张。
- [ ] 三视图对象键在文本扩写前完成读取和图片校验，最终 H3 请求使用准备后的图片数据。

### D. 任务与资产恢复

- [ ] 提交成功后立即保存任务号或保留可恢复信息。
- [ ] 查询异常时不会自动重新提交同一个镜头。
- [ ] 查询状态未知时不会立即丢弃已提交任务，会在时间预算内继续查询。
- [ ] 视频下载后才标记资产有效。
- [ ] 首帧和尾帧提取失败时有明确记录，后续镜头不会把缺失尾帧当作有效级联源。

### E. 批量顺序和额度保护

- [ ] 批量生成按剧本镜头顺序串行执行。
- [ ] 前一个镜头未成功并写入尾帧时，不提交后一个镜头。
- [ ] 已存在有效资产的镜头会被跳过，不重复提交。
- [ ] 失败后批量流程停止并保留明确错误，不自动重试。

## 四、审查通过后的最小真实验证

Claude 审查通过后，仍按下面顺序操作。每一步完成后保存证据，再进行下一步。

### 0. 运行前确认

确认 API 使用包含本轮代码的版本，并确认目标项目不是测试副本。检查：

- 文本 Provider 已配置且启用；
- 图片 Provider 已配置且启用；
- 视频 Provider 为 MiniMax H3；
- 目标项目剧本已确认；
- 已有 `shot_1`、`shot_2` 保持有效，不重新生成；
- `shot_2` 已有 `lastFrameObjectKey`；
- 当前余额和单次预算允许进行一次新镜头测试。

这一步只读，不调用供应商。

### 1. 只生成一个新场景首镜头

如果存在尚未生成的新场景首镜头，优先选择它；否则选择目标项目中尚未生成且属于已有场景的下一个镜头。一次只点击一个镜头的生成按钮。

记录以下信息：

- 项目 ID、镜头 ID、场景 ID；
- 请求前有效资产数量；
- Skill 使用的模式和参考图数量；
- 返回的任务号；
- 最终状态、视频时长、分辨率和是否含音轨；
- `firstFrameObjectKey`、`lastFrameObjectKey` 是否写入。

### 2. 只生成一个同场景后续镜头

首镜头成功且尾帧已写入后，再生成它的下一个同场景镜头。检查：

- 请求模式为 `i2va`；
- `firstFrameObjectKey` 等于前镜头的 `lastFrameObjectKey`；
- H3 请求中没有角色图片和场景图片；
- `cascadeFromShotId` 等于前镜头 ID；
- 新视频首帧与前视频尾帧在构图、人物位置和场景方向上连续。

### 3. 才决定是否继续完整 30 秒

只有前两步都成功，且没有出现 `H3_PROMPT_INVALID`、`PROVIDER_INVALID_RESPONSE`、错误的模式、缺失尾帧或明显人物漂移，才继续生成剩余镜头。

完整目标采用 6 个约 5 秒镜头。同一场景的镜头严格按顺序生成；切换场景时重新使用新场景首镜头参考图。每个镜头保持一个主要动作，避免在一次 H3 请求中安排多个连续事件。

## 五、失败处理规则

| 现象 | 处理 |
|---|---|
| `CASCADE_FRAME_MISSING` | 停止，不产生新请求；检查前镜头视频下载和尾帧提取。 |
| `H3_PROMPT_INVALID` | 记录 `reason` 和 `section`，停止；不要连续点击。 |
| `PROVIDER_INVALID_RESPONSE` | 记录 `stage`、`reason`、任务号和安全状态；先查询已有任务，不重新提交。 |
| HTTP 400 | 保存受限上游错误码和请求 ID，先判断模式、分辨率、图片数量和路径。 |
| HTTP 401 | 检查对应 Provider 的 API Key、地址和授权头，不重复生成。 |
| HTTP 503 | 判断是否为供应商限流、服务不可用或本地配置错误，先看日志，不连续重试。 |
| 视频成功但缺尾帧 | 保留已生成资产，停止后续镜头，修复或补齐尾帧后再继续。 |
| 人物或场景明显漂移 | 保留证据和 Prompt 元数据，暂停完整生成，先审查输入图与级联关系。 |

## 六、审查结果模板

Claude 完成审查后，请填写：

```text
审查状态：PASS / FAIL / NEEDS-EVIDENCE

代码审查：
- 级联：
- Skill：
- 参考图：
- 任务恢复：
- 批量顺序：

发现的问题：
1.

建议执行的最小验证镜头：
- 项目：
- 场景：
- 镜头：

是否允许进行一次真实视频调用：是 / 否
```

只有审查状态为 `PASS`，并且“是否允许进行一次真实视频调用”为“是”，才进入最小真实验证。
