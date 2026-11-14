# 14A 风格库基础验收

日期：2026-09-19。已先编写style-ui-taskbook-2026-09-19.md和任务14，重排02/03/04/12依赖，再实施14A。仅本地；无提交/推送/部署、真实模型调用、数据迁移或Worker/Beat启动。

## 本批使用方式

创建页故事输入下方「新项目画风」可选6种：真人电影写实、国风三维动画、日系二维动画、国风厚涂、水墨动画、美式漫画。选择只更新草稿，不发起生成；点原有创建/生成按钮才保存到新项目。显示选中规则及当前项目已保存名称/版本；刷新可从项目快照恢复。目录异常有明确提示与重新读取按钮。

未选择时保留原有各阶段提示词；旧项目不自动套用新预设。在已有项目页面重新选择，只影响下一次新建，不能修改当前项目。第一版是文字规则卡片；旧项目换风格、个人风格、示意图和收藏仍属14B/C，未完成。

## 实现与输入链路

- production/visual_styles.py：6个版本1预设、服务器快照解析、分阶段规则和视频输入合并。GET /api/visual-styles只读目录；POST /api/projects增加可选stylePresetId，未知ID400且不创建记录。完整规则由服务器生成，项目JSON保存visualStyleProfile，无schema迁移。
- pipeline：拆分/导入预览/旧generate_script入口附加项目规则；故事原文保持不变，纯故事扩写本身未增加视觉风格提示。人物提示词上下文带快照和明确规则；主图/多视图/场景使用对应阶段规则，视频两个H3提示词路径都能收到相同风格。H3参考图模式/分辨率和供应商选择无改动。
- drama_skills.py：选定风格时按已保存快照编译媒介规则，不再从描述关键词猜测画风并混入写实材质兜底；未选风格保留旧路径。沿用现有阶段Skill加载/元数据，并增加styleApplication（local-style-v1），这是本地编译，不声称新增文本模型调用或外部Skill全文执行。
- 图片结果保存styleSnapshot；角色候选被确认后复制到referenceImageStyleSnapshot，场景保存backgroundImageStyleSnapshot，视频资产保存styleSnapshot/styleApplication。已有生产参考复用逻辑保留；本批不判断旧参考是否真的符合新画风，这属于02/05/14B依赖核查。
- 角色三视图仍是现有三次图生图后拼板，本批不改次数/版式。风格规则不自动选择模型、不提高分辨率、不增删准确台词或角色身份。真实画质仍需用户后续验收。

前端新增features/styles/StylePresetPicker.tsx，使用原生radio、明确的已保存/新项目范围、选中规则和加载/错误状态；创建页/types/api/styles接入。桌面两列、390px窄屏单列，键盘可选。

## 验证记录

RED：新增后端8项因目录404/未保存快照/模块缺失失败；前端2项因没有选择器/目录错误状态失败。实现后修复全量兼容问题：参考图辅助函数改为显式传冻结快照，保留旧无项目记录的测试用途；5项浏览器旧断言限定所需错误/对话框，允许目录错误与业务错误同时存在。

| 检查 | 最终结果 |
| --- | --- |
| 新增test_project_styles.py | 12项通过；含6风格、输入捕获、目录/旧项目兼容、临时SQLite重建runtime、H3两路径、确认剧本生场景、损坏规则阻断 |
| pytest test_project_styles.py test_reference_image_prompts.py test_h3_skill_execution.py -q | 33通过 |
| pytest backend/tests -q --tb=short | 684通过，3条件跳过 |
| ruff check backend/src backend/tests | 通过 |
| mypy backend/src/comicflow | 71源文件通过 |
| pnpm --dir frontend build | TypeScript/Vite通过 |
| node --test frontend/tests/*.test.mjs | 27通过 |
| pnpm --dir frontend exec playwright test | 60通过，新增2项风格交互 |
| git diff --check（本批已跟踪文件） | 通过，仅既有LF/CRLF提示 |

后端使用var/verification/style-library-20260919/run_offline.py清理业务环境、memory/mock、阻断外联socket（仅放行Windows asyncio内部socketpair），FFmpeg只处理本机合成样本。3跳过为2项外部脱敏项目fixture和1项Docker基础设施smoke；1个既有Starlette/httpx弃用警告。SQLite临时库不等同真实PostgreSQL迁移测试。

前端VITE_API_PROXY_TARGET=http://127.0.0.1:9，新风格用例拦截全部API，选择阶段业务写请求0，创建阶段仅预期项目创建与故事fixture请求。已有用例未拦截的辅助GET出现ECONNREFUSED日志，未连真实后端；60项全部通过。桌面/窄屏截图检查完成，预设示意使用测试数据，不是生图效果样张。

最终日志：var/verification/style-library-20260919/backend-final.txt、frontend-e2e-final.txt、frontend-node.txt；截图desktop.png/mobile.png。同目录保留首次失败日志用于追踪。改动前副本与12文件清单在var/change-backups/style-library-20260919/，这些目录均被Git忽略。不要用全仓reset回溯，根目录还有其他未提交工作。

## 接续任务

下一批02+12B：准备单展示实际模型/768P等参数/快照/参考用途/对白及提示词处理模式，移除画面固定参数与无效控件。再做03+04A持久作业与恢复；随后05/06/14B连续性、角色整板、旧项目换风格和个人风格；大范围视觉改版和示意图库后置。部署与旧数据迁移继续暂停。
