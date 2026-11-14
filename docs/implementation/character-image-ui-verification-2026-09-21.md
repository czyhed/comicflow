# 角色图片入口收敛与文字整板交接

日期：2026-09-21。用户已亲自验证文字整板并反馈“效果很好”，本批只整理生成入口和页面信息层级。该反馈不代表视频、万相图生图或所有角色质量均已通过。

## 实际变更

- `CharacterReferences.tsx`：一个“图片生成方式”下拉框和一个“生成图片”按钮，默认文字生成设定板，另可选基于主图生成三视图和单张主图。复用三种既有mutation/API，缺确认主图时禁选图生图；未保存设定/活跃或未知作业仍阻止新提交。
- 候选及独立确认优先展示，其他已确认素材、历史分图和已结束作业折叠。进行中/未知/失败/未应用结果仍显示，安全恢复保留；作业与错误详情可展开，不删除历史。
- `CharacterEditor.tsx`：图片区提前；已有外观和服装时文本助手默认折叠，缺设定则打开。保存新设定不强行收起正在编辑的助手。镜头绑定、单张主图提示词、声音设置折叠。
- `styles.css`：角色图片区、状态、折叠项及窄屏单列布局。保存、草稿采用、素材确认仍分别操作。

本批未改后端、模型配置、Skill或提示词。刷新/切换方式/查看记录不调用模型。

## 补齐此前文字整板的交接

`text-board`：已保存姓名/外观/服装＋项目风格＋本地character-text-board规则 → image绑定 → 一次生成脸部特写＋正面/侧面/背面全身的单张板 → 候选 → 用户确认 → H3人物参考一张板。无主图也可用，不带已有主图或旧单张主图提示词，不额外调用文本模型。实际构图仍由用户看图验收。

原`board`继续使用确认主图和image-edit绑定；`candidate`继续生成单主图。新入口不切换模型配置，不用文生图冒充图生图。当前image为gpt-image-2.5/chat-image，image-edit为wan2.6-image/wan26-image、1536×1024；H3仍768P/context-ir。

用户确认供应商无任务后，第二条未知作业`ijob_2c472b0c37e44689be9edc404bd510a2`在此前已通过存储事务关闭；状态cancelled，原PROVIDER_UNAVAILABLE和1次提交尝试保留，无taskId。证据位于`var/verification/text-character-board-20260921/`。此次UI只折叠已关闭记录，不再关闭/重发/取消供应商任务。

## 本批验证

新增界面用例先因生成方式控件不存在失败，实现后通过。检查单按钮分别提交candidate/board/text-board、切换零请求、默认折叠、错误展开、刷新默认值及390px无横向溢出；既有用例继续覆盖未保存/缺主图/未知锁和候选确认。Mock浏览器不会访问真实供应商。

| 检查 | 实际结果 |
| --- | --- |
| 聚焦角色/图片Playwright | 7通过 |
| frontend：`pnpm build` | 通过 |
| frontend：`node --test tests/*.test.mjs` | 27通过 |
| frontend：`pnpm exec playwright test --reporter=line` | 80通过 |
| `uv run pytest backend/tests -q --tb=short` | 829通过，3条件跳过 |

跳过：两个需要COMICFLOW_OFFLINE_FIXTURE的脱敏夹具用例，一个需要COMICFLOW_INFRA_SMOKE的Docker冒烟。出现既有Alembic/Starlette弃用警告。完整真实隔离数据栈本批未重跑；09B的六镜联调证据继续见原报告，不列为本批新增通过。integration用例选择器已随新入口更新，未宣称整套integration重验。

在实际5173角色页只读检查新选择器、折叠项和现有素材；前端和代理health均200。前端Vite热更新即可，不需API/Worker/Beat重启。桌面/390px截图在`frontend/test-results/character-image-workspace--78671-secondary-content-collapsed/`；Mock图片响应204只用来隔离外网，截图中的Mock缩略图不能用于判断供应商出图质量。

## 回溯与下一步

编辑前副本：`var/change-backups/character-ui-20260921/`。保留此前全部未提交改动，无整体回滚。代理本批真实模型调用0，业务数据写入0，未提交/推送/服务器部署或迁移。

用户刷新 http://127.0.0.1:5173/ 后检查角色页布局即可，不需要为了验证界面重生图片。复用已满意且明确确认的板，下一批检查相邻两镜的实际参考和动作准备单，再由用户逐镜生成/观看/采用；满意后完成约30秒作品。迁移演练与服务器更新后置，不再重做已完成角色模块或泛化提示词优化。
