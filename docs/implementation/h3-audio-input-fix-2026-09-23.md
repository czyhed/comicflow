# 《末班车》镜头1：环境声被当作旁白

2026-09-23。用户反馈视频音频/旁白错误并指定《末班车》镜头1。本批核对桌面H3 API Skill、项目内H3写作指南、已保存生成作业及当前剧本，只修正输入和无台词镜头的校验；没有重新生成、部署或迁移。

## 确定的输入错误

项目 `prj_f9f6e04d5dd7`，作业 `vjob_b24249e1be7d4b939a5d623636cfa23e`，2026-09-23 06:45 UTC 成功。用户已实际生成视频，此结果更新此前“远端503、未有成功生成”的历史状态。本批没有重查远端就绪接口。

冻结的shot和当前剧本均为：

```json
{
  "dialogue": "",
  "narration": "暴雨声、车门气动声、雨点敲打车顶声",
  "soundscape": "暴雨声、车门气动声、雨点敲打车顶声"
}
```

`compiled.submittedPrompt`明确要求“以下为画外旁白，逐字保留”并跟着上述音效描述。恢复参考图占位URL后，离线prepare_preview与实际submittedPrompt逐字相同，断言环境音不应出现在台词段失败：`S1_SOUND_EFFECTS_REQUESTED_AS_SPOKEN_NARRATION`。因此存在确定的错误输入；本批未做音轨试听/语音识别，不能将全部音质问题都归因于这一点。

API Skill的生成接口通过prompt表达说话内容，dialogue_language可选，不存在独立narration请求字段。此任务compile_prompt=false，本地无文本模型扩写；不是仙宫云二次编译把已正确的环境声字段转换成旁白。项目内H3指南也区分voiceover、对白和overall_soundscape。未改远端编译开关或增加付费文本调用；是否使用平台六段式编译与其他模型音质问题不在本次已证实结论内。

## 根因修正与范围

旧剧本仍保存错误narration。先前提示词收尾虽已把环境声指向soundscape，但脚本输出末尾及多处校验仍要求每镜至少一项人声非空，阻碍保留纯环境音镜头。本批统一为：有非空对白/旁白时兼容省略另一项；无台词时两项明确设为字符串空值。全部缺失、只给空白一项且遗漏另一项、错误类型仍拒绝。旧audio.dialogue=[]格式继续兼容。前端不再把明确无台词作为缺陷。

修改现有文本提示、消息契约、预览、保存确认/新增镜头及旧格式验证，不建立关键词猜测或自动清空旁白的启发式规则。用户写入的真正旁白仍逐字保留。

## 本机保存与恢复证据

- 私有备份：`var/verification/h3-audio-20260923/before.json`，含原项目及原作业；不提交。
- 全量验证后重启当前 `local-runtime-api-1` 和 `local-runtime-worker-1` 加载修复，Beat和前端保留运行；Worker ping返回1节点pong。
- 经现有PATCH script及expectedVersion=8修正仅s1的narration为空，同步其派生dialogueReview；环境音、配乐、台词、人物、参考图、动作与其他镜头保持原值。项目version8→9，仍为awaiting-confirmation，未代替用户确认整份剧本。
- 原剧本进入scriptVersions；两条历史视频记录和对象键均保留，已完成作业不改写、不重发。
- 真实API只读准备单ready=true，speech两项为空、0字/0秒，提交文本要求“无对白、无旁白，不新增人声”，音效仅出现在环境声段。仍为6秒/0.5P/544×960/仙宫云协议；calls.text=0/video=1是未来生成预计次数，并非本批调用数。
- 操作前后视频5成功/1失败、图片4成功/2取消、151条已发布outbox均未增加；没有在途生成任务，没有新的真实模型请求。

同项目s4也发现narration与纯音效soundscape重复（暴雨/脚步/河水声），本批未修改或生成该镜头；后续生成前需核对并修正。不能宣称历史所有镜头已清理。数据库、整个MinIO、原解密密钥与Redis正式切换继续保留，7C暂停。

## 验证

- 先复现实际提交错误与脚本显式无台词被拒绝，再修复；新增适配器预览、编辑确认/历史保留和H3 multipart测试。
- `uv run pytest backend/tests -q`：929通过、3条件跳过。首次全量发现旧格式及旧契约两项失败，修正兼容并再次全量通过。
- `uv run ruff check backend/src backend/tests`、`uv run mypy`：通过，94源文件。
- `npm --prefix frontend run build`：通过。
- 前端 `npx playwright test tests/e2e/native-audio-workspace.spec.ts tests/e2e/script-preview-commit.spec.ts --workers=1`：13通过，所有业务与外部请求拦截。

输入已修正不等于现有视频音轨已修复。用户刷新后检查s1准备单，再自行决定是否生成新候选验证；本批不代点付费生成。
