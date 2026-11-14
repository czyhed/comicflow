# 全流程浏览器人工验收指引（真实文本 + Mock 媒体 + 真实 FFmpeg 导出）

日期：2026-09-06
范围：本地 Docker 正式栈（postgresql runtime），浏览器 `http://127.0.0.1:5173` 连 Docker API（`http://127.0.0.1:18000`）。
模式：**文本生成 = 真实百炼 qwen**（`PROVIDER_MODE=real`）；**画面/音频/口型 = Mock**（真实媒体适配器未与百炼核验，见 issue 09）；
**合成 = 容器内真实 FFmpeg**（`COMICFLOW_COMPOSITION_PROVIDER=ffmpeg`），导出为可播放 MP4。

## 前提（由 agent 执行并确认后开始）

1. 仓库根 `.env`（已 gitignore）包含：
   ```
   PROVIDER_MODE=real
   PROVIDER_EVALUATION_GATE=passed
   BAILIAN_API_KEY=<你的百炼 DashScope API Key>
   # 可选：BAILIAN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
   COMICFLOW_COMPOSITION_PROVIDER=ffmpeg
   ```
2. `docker compose up -d` 重建 api/worker/beat（透传 provider 环境变量，未配 `.env` 时默认 mock 不变）。
3. `GET http://127.0.0.1:18000/health` → `{"status":"ok"}`。
4. 真实文本冒烟通过：`python var/acceptance/real_text_smoke.py` → `REAL TEXT SMOKE PASSED`（证明 qwen 链路可用）。
5. 启动前端：`frontend` 目录下
   `VITE_API_PROXY_TARGET=http://127.0.0.1:18000` + `vite` dev server（5173），`/api`、`/health` 代理到 Docker API。
6. 浏览器打开 `http://127.0.0.1:5173`（应显示 "Mock 创作环境"，创建首个项目后变为 "项目已同步"）。

## 验收步骤与预期证据

### A. 自动全流程（真实文本）

1. **创建并生成故事**
   - 保留默认故事文案或改一句；时长选 60 秒 → 点 **生成故事文本**。
   - 预期：顶部出现阶段文案与"生成资产"进度；完成后显示"故事文本已生成"可编辑文本（**真实 qwen 产出**，明显长于默认输入、非模板句式）；右下出现 **进入剧本模块拆分**。
   - 备查：文本来自真实模型（区别于 Mock 的确定性句式）。
2. **保存文本（可选）** → **保存故事文本**。
3. **剧本拆分（预览→确认）**
   - 点 **进入剧本模块拆分** → 剧本工作区出现"剧本拆分 + 创建页已生成故事文本"。
   - 点 **拆分为剧本** → 出现"剧本拆分预览"（剧本标题、场景列表、逐镜头画面/对白/旁白、summary 计数；60 秒应约 3 场景 / 8-10 镜头）。
   - 点 **确认并进入剧本编辑器** → 进入编辑器（"剧本编辑器"标题），可改剧本标题/场景五元组/镜头字段。
4. **确认剧本**
   - 点 **确认剧本并生成分镜** → 跳转分镜工作区；顶栏会话状态反映 `storyboard-ready · ready/running`。
5. **媒体自动生成（会话推进，Mock）**
   - 顶栏会话状态显示 `storyboard-ready · ready`（若仍显示 `script-completed · ready` 属会话影子状态滞后，直接推进即可）。
   - 连点顶栏 **推进**（每次间隔 2-3 秒）：状态依次 `visual-completed → audio-completed → composition-queued`，
     再等 1 次推进/自动完成到 `exported · completed`（画面/音频/口型/时间轴由自动会话逐镜头补齐）。
   - 备查：自动模式已覆盖全部镜头媒体；单镜头"重新生成"仍可在各工作区使用（画面工作区对无资产镜头有"生成当前镜头"；
     声音工作区仅在时间轴已存在时提供"重新生成对白与口型"）。
6. **核验画面/音频产物**
   - 切 **画面**：左侧每个镜头显示 **已生成**（9 个）。
   - 切 **声音**：出现"音画时间轴"，拖动"镜头播放头"，动作/表情/对白/字幕/口型轨随播放头高亮。
7. **合成与导出（真实 FFmpeg）**
   - 切 **导出**：自动会话完成后直接显示 **导出包已就绪**（若未自动合成，点 **开始合成** 并等待）。
   - 点 **下载导出包** → 浏览器直开真实 `video.mp4`（后端清单新结构 `downloads`，预签名 URL 经 `S3_PUBLIC_ENDPOINT` 指向
     `http://127.0.0.1:19000`，宿主浏览器可直接下载）。
   - 预期文件：`video.mp4`（可播放，9:16 1080×1920，H.264/AAC，**逐镜头文字卡成片，长度约等于全剧本时长**，60s 约 9 张卡片）
     + cover.jpg + subtitles.srt（逐镜头字幕）。文字卡由 Pillow+FFmpeg 渲染；接入真实 AI 画面/配音后由模型素材替换卡片。
8. **刷新恢复**
   - 在任一中间步骤刷新页面：项目/剧本/资产状态应从后端恢复，不丢已确认剧本。

### B. 导入内容并整理（可选）

- 新建项目入口选 **导入内容并整理** → 粘贴你自己的故事/剧本 → 点 **拆分为剧本**（创建 import 项目并即时预览）→ 预览 → 确认 → 打开编辑器 → 确认剧本 → 分镜。
- 说明（已按真实行为核验）：自动媒体链路只随 **automatic 会话的"推进"** 提供；import 项目（非 automatic）**声音工作区没有"首次生成音频"入口**（仅时间轴已存在时可"重新生成对白与口型"）。因此浏览器验收的完整画面→音频→导出以 **A 全自动入口**为准；import 项目验收至 confirmed-script + 画面工作区逐镜头生成即可，导出可在**导出**工作区点 **开始合成**（无时间轴时输出退化为首镜头时长的占位视频）。
- 后端能力注记：API 层已实测 import_story 项目可完整走到 FFmpeg 导出（画面/音频/口型/时间轴 + MP4），仅 UI 侧暂缺首次音频入口。

## 需要反馈给 agent 的证据

- 每步成功/失败 + 失败时的屏幕错误文案（红色 alert 的 error 码，如 `PROVIDER_*`/`VERSION_CONFLICT`）；
- 步骤 7 的导出文件名与大小、是否可播放；
- 任意刷新恢复异常或与预期不符的界面行为。

## 不在本轮范围（验收时以 Mock 为准）

- 真实视觉（wan-video）、真实 TTS/口型适配器端点未与百炼核验（issue 09 ready-for-human）；`COMICFLOW_COMPOSITION_PROVIDER` 之外的媒体真实调用不验证。
- guided 模式完整移除仍属后续清理切片。
