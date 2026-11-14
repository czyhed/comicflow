# 任务2：角色模块拆分验收

日期：2026-09-20。范围：任务书v2的15B、15C-character，本地离线完成。下一项是06A按用途生成角色提示词；一次图生图整板和图片持久作业属于后续任务4。

## 实际交付和职责

| 位置 | 职责与边界 |
| --- | --- |
| `backend/src/comicflow/production/character_assets.py` | CharacterAssets负责角色卡读取/保存、提示词预览、主图候选/确认、旧三视图生成/拼板、旧直接安装参考图。显式接收项目存储、角色存储、文本/图片Provider、资产存储、共享锁和签名回调，不接收整个Pipeline。 |
| `backend/src/comicflow/production/reference_images.py` | 提取角色与场景共用的原图片请求准备、Skill元数据和图片结果校验；没有新增模型适配协议。 |
| `backend/src/comicflow/production/pipeline.py` | 保留原公开入口并委托角色模块；每次使用当前请求选定的Provider，锁及签名缓存仍共享。同步剧本角色和绑定镜头涉及剧本版本，继续留在原编排层。 |
| `backend/src/comicflow/api/characters.py` | 提取13个角色路由，沿用原URL、schema、权限校验和请求级模型选择。角色/场景共用的旧reference路由继续由app入口分派。 |
| `frontend/src/api/characters.ts` | 集中角色API方法，复用client原request及错误/认证处理。 |
| `frontend/src/features/characters/CharacterWorkspace.tsx` | 项目与角色选择、列表和同步。 |
| `frontend/src/features/characters/CharacterEditor.tsx` | 角色草稿、提示词预览/采用、保存及镜头绑定。 |
| `frontend/src/features/characters/CharacterReferences.tsx` | 参考图请求状态、候选/确认/三视图展示，与编辑器共享忙碌状态；角色切换沿用原key重置草稿。 |

签名回调只提供对象URL，不暴露Pipeline内部对象；共享锁保持原并发行为。未引入新框架、全局状态层、数据表或迁移。

## 保持的流程

1. 图片生成仍使用保存的referenceImagePrompt；空值时使用原角色设定组装逻辑，Skill/风格规则未改。
2. 新主图先保存候选，由用户确认；角色归属、项目版本和生成期间编辑冲突检查保留。
3. 已确认主图仍分别生成正面、四分之三、侧面三个视角，再本地将主图和三图拼成1536×1536的2×2板。**本批没有改成一次生成整板，也没有改成正面/侧面/背面。**
4. 同一来源的完整三图可复用；部分失败保留已成功图片且不自动重试。旧直接reference入口保留原直接安装语义。
5. 下游视频读取仍收到主图信息及referenceBoardObjectKey；原场景图片流程和角色模型用途选择保持兼容。

## 验证证据

结构抽取前新增`backend/tests/test_character_module_contract.py`并通过原Pipeline：覆盖候选→确认→三个视角→实际本地拼板→视频准备、完整结果复用、第二视角失败保留首图、生成期间编辑冲突及跨项目拒绝。

冻结请求位于`backend/tests/fixtures/character-requests-before-split.json`，捕获原实现主图及三个视角的完整准备输入，包括提示词和Skill元数据。只把随机shot.id替换为固定操作ID，不删除提示词或规则字段。12个原方法与新模块方法的AST比较一致；此比较只是辅助证据，不能替代调用链测试。

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 同组角色/图片/视频引用聚焦测试 | 原实现56通过；核心抽取后56通过；路由抽取后56通过 | `var/character-split-baseline.txt`、`character-split-after-core.txt`、`character-split-after-routes.txt` |
| 完整后端 | 755通过，3条件跳过 | `var/character-split-backend-regression.txt` |
| Ruff / Mypy | 通过；Mypy检查81个源文件 | 本次终端运行 |
| 前端生产构建 / Node | 通过 / 27通过 | 本次终端运行 |
| 角色页聚焦浏览器 | 3通过 | 新增刷新/角色切换/独立确认及视角生成场景 |
| 全部Playwright | 74通过 | `var/character-split-playwright.txt` |
| 方法结构比较 | 12项一致 | `var/character-split-method-comparison.json` |

后端命令：`.venv/Scripts/python.exe -m pytest backend/tests -q --tb=short`、`-m ruff check backend/src backend/tests`、`-m mypy backend/src`。前端目录命令：`pnpm build`、`node --test tests/*.test.mjs`、`pnpm exec playwright test`。

浏览器新增场景以拦截的API和图片验证：生成候选后刷新不会重复生成，确认前无三视图操作，确认和三视图分别点击，切换角色不会串用草稿或图片。后端测试另行捕获实际内部三个图片调用，不能把浏览器的一次三视图HTTP请求说成只有一次供应商生成。

3项跳过是2个需要外部脱敏项目夹具的测试，以及1个未启用的Docker基础设施冒烟测试。本批没有重新执行真实PostgreSQL/Redis/MinIO/Worker联调；假供应商回归不能证明真实模型画质或当前业务服务在线。

## 已确认的原有缺口，交后续任务修复

- **旧板失效缺口：** `save_project_character`修改外观/服装/生图提示词会清理主图和视角；`approve_character_reference_candidate`也会清理视角，但都没有同步使旧referenceBoard失效。VideoPreparation仍读取该板，存在把旧身份图片传入视频的风险。本批按结构任务保持原行为；任务3处理草稿与有效资产的区分，任务4以主图来源版本约束板的采用/读取，并先补失败测试。
- **部分失败重试重复调用：** 旧循环保存成功视角，但手动重试会重新遍历全部三个视角，不是仅补缺失图；原页面提示不准确。本批没有增加自动重试。任务4改为一次整板和持久记录，不在此扩展旧三图恢复系统。
- **旧素材布局：** 现有板是主图加三个视角的四格板。任务4的一次正/侧/背板尚未实现，旧素材不会因本次拆分自动重画。

以上来自原实现，不将“拆分回归通过”写成“所有素材失效与恢复问题已经解决”。当前不建议为本次结构整理专门消耗额度；下一次角色流程的真实画质验证安排在任务4后，由用户点击。

## 回溯与下一步

修改前副本在`var/change-backups/character-module-split-20260920-211031/`，包含当时的源码、测试和相关文档；06工单另补同目录副本。原有未提交改动保留，本次未提交/推送Git。

真实文本/图片/视频调用均为0；未重启业务API/Worker/Beat、修改运行配置、执行数据库迁移或部署。源码完成不代表业务镜像已更新。

下一项06A：区分“完善角色设定”和“只润色主图提示词”，同步调整请求/响应校验、文本上下文和页面草稿采用；只返回本次需要的字段，保留旧内容，不删除仍用于生图的提示词。完成后再进入一次整板及最小图片记录。
