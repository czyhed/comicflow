# 本地 Docker 正式栈部署验收证据

日期：2026-09-06
运行时：`COMICFLOW_RUNTIME=postgresql`（docker compose 全栈）；前端静态预览 + Playwright（路由级 mock，不依赖后端）

## 范围

按 `docs/PROJECT_ENGINEERING_RULES.md` 阶段 0-6 / `docs/superpowers/plans/2026-09-04-creation-runtime-stabilization.md` T0-T7，
对"创建 → 自动/导入 → 剧本预览→确认 → confirmed-script → 刷新/重启恢复"的本地闭环做正式运行时验收，并跑绿全部门禁。

## 环境

- Docker Desktop 28.5.1（WSL2 backend，需完整权限会话）；compose：postgres:16-alpine / redis:7-alpine / minio / api / worker / beat / migrate / object-store-init
- 宿主映射：API `127.0.0.1:18000`、PG `15432`、Redis `16379`、MinIO `19000`
- 本机 ffmpeg 8.1.2；前端工具链用现成 `frontend/node_modules/.bin`（tsc/vite/playwright）
- `uv` 缓存与 pytest 临时目录在受限沙箱被拒 → 门禁命令在完整权限会话执行（与本仓库代码无关的环境限制）

## 命令与结果

### 1. 全栈启动与迁移
```
docker compose config --quiet            # ok（9 services）
docker compose up -d --build             # api/worker/beat Up；postgres/redis/object-store Healthy；migrate、object-store-init 成功退出
GET http://127.0.0.1:18000/health        # {"status":"ok"}
```
- Alembic：`migrate` 服务执行 `alembic upgrade head`（0001_initial）成功。

### 2. 基础设施烟雾测试（连真实 PG/Redis/MinIO + outbox→Celery）
```
COMICFLOW_INFRA_SMOKE=1 pytest backend/tests/test_infrastructure_smoke.py
# 1 passed
```

### 3. 全量门禁
| 门禁 | 结果 |
| --- | --- |
| pytest（全量，`-p no:cacheprovider`） | 130 passed, 1 skipped（skipped=infra smoke 未设 env 的默认跳过项之外） |
| ruff check backend/src backend/tests | All checks passed |
| mypy --package comicflow | Success: no issues in 41 source files |
| tsc -b（frontend） | exit 0 |
| vite build（frontend） | exit 0（1743 modules） |
| Playwright e2e | **33 passed**（修复前基线 25 passed / 9 failed） |

### 4. e2e 对齐（本次修复，全部路由级 mock）
- 3 个用例从过时的 `POST /script/split`（旧"拆分直达编辑器"架构）改为当前"预览→确认"架构
  （`POST /script/preview` + `PUT /script/preview` 精确提交、不重新生成），见
  `frontend/tests/e2e/script-preview-commit.spec.ts` 的既有断言口径：
  - `create-project.spec.ts`：creator can generate a script and enter the script workspace；
    script workspace previews a split and can retry a failed preview
  - `production-flow.spec.ts`：creator can generate visual audio and composition assets …
- 创建页入口已收敛为 `automatic` + `import_story/import_script`（两个 radio），逐步确认（guided）仅对旧项目续聊
  （依据 09-05 规约与审计阶段 A"删除 guided 新请求的 Playwright 覆盖"）：
  - guided 新入口用例改/删：bounded chat、guidance 失败重试改为"已保存 guided 项目续聊"语义；
    direct-generation preview 用例删除（覆盖已被 guided 续聊与剧本编辑器用例承接）；
    "切换到 guided"用例改为断言自动项目不提供 guided 入口；endpoint 隔离用例改为 seeded guided 项目；
    额度不足用例改为 automatic story 生成（`INSUFFICIENT_CREDIT` 语义不变）
  - 保留：saved projects … resume guided chat（旧项目兼容读取）

### 5. postgresql 正式运行时两条主流程 HTTP 实测（`var/acceptance/two_flow_http.py`）
```
[auto]   created prj_fb3473e25e7b mode=automatic
[auto]   story text generated (610 chars) → preview 9 shots expectedVersion=3 → commit → confirm
[import] created prj_e6b7b31061de mode=import_story（stage 初始 story-generated，用户文本保留）
[import] preview 9 shots expectedVersion=1 → commit → confirm
[ok] snapshot: stage=storyboard-ready version=4 shots=9 scenes=3（auto）
[ok] snapshot: stage=storyboard-ready version=2 shots=9 scenes=3（import）
[ok] GET /api/projects lists both ids
ALL TWO-FLOW ACCEPTANCE CHECKS PASSED
```

### 6. API 重启恢复（docker compose restart api → /health ok 后）
```
[automatic] prj_fb3473e25e7b stage=storyboard-ready version=4 scriptVersions=1 shots=9 story=610ch
[import]    prj_e6b7b31061de stage=storyboard-ready version=2 scriptVersions=1 shots=9 story=161ch
RECOVERY OK
```
- 项目/剧本/不可变剧本历史（scriptVersions）/generatedStoryText 在 API 容器重启后完整可读，项目列表仍含两项目。

## 结论

本地 Docker 正式栈（postgresql 运行时）验收通过：两条主流程均可到达 confirmed-script（storyboard-ready），
预览→确认不重新生成、刷新/重启恢复成立，pytest/ruff/mypy/typecheck/build/Playwright/ffmpeg/infra-smoke 全部门禁绿。
仓库内未提交的实现改动（约 4000 行，属本切片）按主题提交收口。

## 追加：全流程（媒体 Mock + 真实 FFmpeg 导出）链路验收（同日）

按 2026-09-06 范围决策（见 `docs/PROJECT_ENGINEERING_RULES.md`），把验收从 confirmed-script 延伸到最终导出，供浏览器人工验收（指引见
`docs/release/2026-09-06-full-flow-browser-guide.md`）。以 `COMICFLOW_COMPOSITION_PROVIDER=ffmpeg`（容器内真实 FFmpeg）+ 媒体 Mock 重建栈后，
`var/acceptance/full_flow_http.py` 实测输出：

```
[1] created prj_ac053243a94b mode=automatic
[2] story ok chars=610
[3] confirmed script: 3 scenes / 9 shots
[4a] visual keys=[characterRefs durationMs fps height id inputVersion mediaType modelVersion objectKey provider shotId type valid width]
[4b] audio keys=[asset lipSync projectVersion timeline] asset=True lipSync=True timeline=True
[4] visuals+audio ok for 9 shots
[5] composition queued job=job_fabd1a82dbf4
[6] export manifest files=[video.mp4 cover.jpg subtitles.srt]
[7] downloaded 128159 bytes (预签名 URL 经 S3_PUBLIC_ENDPOINT 指向宿主 127.0.0.1:19000)
[8] ffprobe: codec h264 / 1080×1920 / 30fps / duration 7s / size 128159
FULL FLOW (mock media + real ffmpeg export) PASSED
```

配套根因修复（本轮提交）：
- `providers/s3.py`：`S3AssetStore.public_endpoint`（`S3_PUBLIC_ENDPOINT`）把预签名 URL 主机改写为宿主可访问端点；新增纯函数
  `rewrite_presigned_host` 及单测 `backend/tests/test_s3_asset_store.py`。
- `docker-compose.yml`：api/worker/beat 透传 `S3_PUBLIC_ENDPOINT`（默认 `http://127.0.0.1:19000`，未覆盖则不影响其他环境）。
- 前端导出：`GET /export` 新清单结构为 `downloads: {文件名: url}`，`ExportWorkspace` 优先取 `downloads['video.mp4']` 直开下载，
  兼容旧 `downloadUrl`，其余回退为保存 manifest JSON。

遗留说明：导出已升级为**逐镜头文字卡成片**——每个镜头一屏 1080×1920 文字卡（场景/镜头号/画面描述/动作/对白/旁白，Pillow 渲染中文），
按各镜头时长拼接成全片（9 镜约 60s），并带逐镜头 SRT 字幕；真实 AI 画面/配音/口型仍未接入（issue 09，媒体适配器未与百炼核验）。


## 追加：真实文本(qwen)+ Mock 媒体 + 真实 FFmpeg 导出（同日后段）

在 .env 配 PROVIDER_MODE=real（Key 放 gitignored .env）+ MEDIA_PROVIDER_MODE=mock 后：
- 真实文本冒烟：故事生成 860-939 字符（非 Mock 句式）→ REAL TEXT SMOKE PASSED；
- 真实文本全流程 HTTP：qwen 拆分 3 场景 / 10 镜头 → Mock 媒体 → FFmpeg 导出 60s MP4（2.96MB）→ FULL FLOW PASSED；
- 真实文本无头浏览器全流程（dev 5173 → Docker API）：生成→拆分预览→确认→会话推进自动媒体→导出就绪→下载 URL（127.0.0.1:19000）→刷新 stage=exported → UI DRY RUN PASSED。
配套能力：新增 MEDIA_PROVIDER_MODE（默认跟随 PROVIDER_MODE；=mock 时画面/音频/口型/审核保持 Mock）、TEXT_PROVIDER_TIMEOUT_MS（默认 120000）；含单测 test_runtime_provider_split.py。
遗留：真实媒体适配器仍未与百炼核验（issue 09）；故事/剧本为真实 qwen，片内画面为文字卡占位。

## 追加：真实配音固化(2026-09-06 末段)
- 真实 TTS(Qwen-TTS, dashscope multimodal-generation)全镜头配音:对白或旁白任一即合成真声;10/10 镜头 bailian wav(2.2–10.8s),24000Hz,存 MinIO;
- 导出混音:每镜头配音按时间轴对齐混入(有语音段用 aformat/apad/atrim+concat,无语音段静音),成片音轨 AAC,volumedetect mean≈-27dB/max≈-7dB;
- 稳定性:容器 DNS 间歇解析失败 → TTS 连接级重试 3 次(单测覆盖);时长探测优先 ffprobe(规避 RF64 大头误读);
- 实测:自动全流程 → 真实 qwen 拆分 10 镜头 → 10 段真实配音 → FFmpeg 60s MP4(2.9MB)下载通过。
- 环境变量: TTS_PROVIDER_MODE / TTS_PROVIDER_MODEL(qwen3-tts-flash) / TTS_VOICE(Cherry);换音色改 TTS_VOICE。

## 追加：真实画面（wanx 文生图关键帧）(2026-09-06)
- BailianImageProvider：dashscope 文生图异步任务(n=1, 720x1280 竖版)提交→轮询→下载→PNG 入库；实测 6 镜头全部 provider=wanx、media=image,每张 14–20s；
- 导出：每镜头关键帧作为卡片背景(cover-crop+字幕带)，无图回退文字卡；成片 1080x1920,帧采样 ~1 万色(真实图像非纯色),配音 mean≈-28dB；
- 开关：VISUAL_PROVIDER_MODE=real(默认 wanx2.1-t2i-plus)；想省钱可置空回 Mock。

## 追加：画面动态化小样（wan 文生视频）(2026-09-06)
- BailianVideoProvider 实测：wan2.2-t2v-plus 异步 1080*1920×5s,单段生成约 85s(85.1s/85.5s),文件 4.0–7.2MB;h264/1080x1920/5s 可播放；
- 注意：wan2.2-plus 竖版尺寸须 1080*1920(或 480*832)，720*1280 会被拒；
- 结论：动态镜头链路可行；下一步把每镜头关键帧/文本→视频接入流水线与成片拼接(更大的改造)。
