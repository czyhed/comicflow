# MiniMax H3与人物参考图：网页资料登记

后续实读落盘见[社区归档报告](h3-community-archive-2026-09-22.md)：222项索引、72条MIT重建全文，150条作者原稿仍仅索引；ZeroLu原始JSON及7条正文/1条missing已保存。下方“尚无JSON副本”等为归档前状态，不再作为当前结论。有限源码应用见[执行记录](../implementation/prompt-inventory-verification-2026-09-22.md)。

更新：2026-09-22。用于后续提示词库和风格库增量；此文件实际保存了来源、既有调研结论与待补项，没有声称完整采集全站。本文结合当前对话已读取的页面和仓库内既有研究文档整理，本轮未重新访问这些网站、播放样片或调用模型。

## 1. 来源与归档状态

| 来源 | 已知阅读范围 | 本地持久化情况与限制 |
| --- | --- | --- |
| [tryminimax提示词页](https://tryminimax.asia/zh/minimax-h3-prompts) | 此前页面统计约222条；查看过电影叙事、运镜、人物表演、对白音效、参考图一致性、动画等分类，确认存在“展开全文” | 本文件保存分类和规则摘要；**未完成222条全文归档**，不能把卡片摘要当全文，也没有可靠逐条读取清单 |
| [xianyu110资料仓库](https://github.com/xianyu110/awesome-minimax-h3-prompts) | tryminimax页面标示的资料来源 | 尚未完成与网页逐条对照，不因链接存在而声称已经读取/去重完整数据 |
| [ZeroLu仓库](https://github.com/ZeroLu/awesome-minimax-h3)及[中文README](https://github.com/ZeroLu/awesome-minimax-h3/blob/main/README-zh.md) | 同一仓库两个入口；此前读了README、[案例JSON](https://github.com/ZeroLu/awesome-minimax-h3/blob/main/data/community-x-minimax-h3-cases.json)及[导入脚本](https://github.com/ZeroLu/awesome-minimax-h3/blob/main/scripts/import-x-showcase.py) | 当次JSON有8条，其中7条标complete、1条missing；README展示7条有prompt案例。没有运行导入脚本、下载媒体或安装Skill；本文保存索引与取舍，尚无本地JSON副本 |
| 小红书 | 已有7篇正文及部分成图、评论阅读记录 | [2026-09-21实读文档](../implementation/xiaohongshu-character-prompt-review-2026-09-21.md)已经落盘；不能再说仅看过一篇或全部只在上下文中 |
| 供应商原始资料与现有Skill | 模型手册、H3写作指南、角色提示词官方来源调研已在仓库 | [模型手册](%F0%9F%90%9AMiniMax%20H3%20%E6%A8%A1%E5%9E%8B%20-%20%E4%BD%BF%E7%94%A8%E6%89%8B%E5%86%8C.md)、[H3指南](MiniMax%20H3%20-%20%E8%A7%86%E9%A2%91%E6%89%A9%E5%86%99%20Prompt%20%E5%86%99%E4%BD%9C%E5%85%A8%E8%83%BD%E6%8C%87%E5%8D%97.md)、[角色来源调研](../implementation/character-prompt-source-research-2026-09-20.md)；接口事实仍以实际接入平台文档为准 |

tryminimax是综合库，含电影叙事、运镜、人物表演、对白音效、特效转场、动画二次元、广告产品、动物、参考图一致性、视频编辑。以前记录的分类数量为43/11/23/8/21/45/52/3/9/7，合计222；这些是上次页面计数，不代表本轮逐条核验或全部适用于漫剧。

纠正错误链接归属：用户先前提供的`245c01fc-b57f-4279-880f-d9f501d8e002`和`df4942db-ce48-4488-a878-c35e02819aa2`来自**仙宫云**，不是小红书note ID。此前代理把它们拼到小红书URL得到404，不能据此宣称原文已失效。正确链接为[仙宫云案例一](https://www.xiangongyun.com/image/detail/245c01fc-b57f-4279-880f-d9f501d8e002)、[案例二](https://www.xiangongyun.com/image/detail/df4942db-ce48-4488-a878-c35e02819aa2)，原用户另给[案例三](https://www.xiangongyun.com/image/detail/8517a83f-a46c-4ed0-b529-4910d97bcf80)；本轮只校正来源，未重读。

## 2. ZeroLu案例索引与取舍

这是对先前读取JSON的归纳，complete是仓库采集标记，不是生成质量或可复现性认证。中文README标题中文化，prompt保留英文，不证明英文比中文好。

| ID | 案例 | 原帖 | 提炼与限制 |
| --- | --- | --- | --- |
| x-mm-h3-01 | ABC儿童动画 | [umesh_ai](https://x.com/umesh_ai/status/2084227244533411987) | 时间段有可见动作与同步声音；字母形变、字幕和儿童教育目标不灌入普通漫剧 |
| x-mm-h3-02 | 街头摄影师抓拍 | [aiwithaly](https://x.com/aiwithaly/status/2087102541146522089) | 发现→取景→拍摄→展示→说话→继续走，借鉴因果动作；不照搬人设或假定短时长能完成全部动作 |
| x-mm-h3-03 | 悬崖城市追逐 | [umesh_ai](https://x.com/umesh_ai/status/2082499539735588916) | 连续空间、方向和明确落点；炫技运镜不作为普通对白镜头默认值 |
| x-mm-h3-04 | 本地生成展示 | [venturetwins](https://x.com/venturetwins/status/2084298391107055692) | promptStatus=missing，只存索引，不补造原文 |
| x-mm-h3-05 | 办公室笑场 | [techhalla](https://x.com/techhalla/status/2084838553943449908) | 15秒分阶段动作、反应和结束状态；借表演节奏，不照搬人物身份 |
| x-mm-h3-06 | Jim/Dwight讨论编码智能体 | [venturetwins](https://x.com/venturetwins/status/2084353489061499021) | 归档prompt很短；公开文字完整不等于输入素材、参数和复现条件完整 |
| x-mm-h3-07 | 节拍角色环境展示 | [aimikoda](https://x.com/aimikoda/status/2086553240448241802) | 角色图负责身份，音频负责节奏；15秒/5环境/30镜是蒙太奇示例，不作为漫剧通用规则 |
| x-mm-h3-08 | AI替代不了Joey | [TechieBySA](https://x.com/TechieBySA/status/2084600512180113820) | 说话人、原台词、停顿、视线和对方反应分开；语音时长仍需按实际台词检查 |

## 3. 跨来源可复用规则，先与代码查重

| 规则 | 来源依据 | ComicFlow应用与边界 |
| --- | --- | --- |
| 明确每份参考素材的职责 | ZeroLu-07、tryminimax一致性类、用户贴入的中文结构 | 角色身份、空间布局、尾帧连续性分开；编号来自实际manifest，不杜撰参考音频或视频 |
| 用可观察动作写过程和结果 | ZeroLu-02/03/05、tryminimax叙事类 | 起始站位→实际接触/位移→完成位置；门槛/台阶和机位必须使动作可见，结尾停在完成态 |
| 按真实时长安排动作 | 时间分段案例 | 5秒/10秒各按duration编译；不为模板自动增加付费时长，已有原稿时间安排优先 |
| 对白、旁白和环境声分别指定 | ZeroLu-08及对白类 | 台词逐字、说话人和一次性表达、反应留白；旁白不强制人物做口型，音乐不盖住人声 |
| 身份板兼顾脸部和全身可读性 | 小红书实读及用户贴入整板范例 | 一张头肩特写＋正/严格侧/背全身；统一骨相/服装/比例，不默认增加表情、尺标、文字、换装 |
| 画面质感写具体材质/光线 | 角色官方来源调研、小红书媒介区别 | 衣料层级、光源方向、高光控制、皮肤/线面/笔触匹配当前风格，避免万能“高级、8K”堆叠 |
| 风格与题材分开 | 已有工单14决策 | 仙侠/都市/悬疑不自动变成另一套媒介预设；先完善现有6种风格，不建几十种交叉组合 |
| 样片不是接口或稳定性证明 | 社区数据/评论证据边界 | 不从帖子推断模型别名、免费额度、Seed支持、H3模式互斥或成功率，协议以目标服务文档为准 |

现有[中文编译器](../../backend/src/comicflow/providers/h3_context_ir.py)、[视频准备](../../backend/src/comicflow/production/video_preparation.py)、[风格模块](../../backend/src/comicflow/production/visual_styles.py)已包含上述多项。下一批要比较具体缺口，不能把现有行为包装成待新建功能。

## 4. 尚未完成的全文资料归档

用户要求记录tryminimax“展开全文”，该请求**尚未完成**。不能把本文件的规则摘要宣称为全部正文已存。

接续时先查看网页或其公开原始数据，完整读取后再落盘；按小批次保存以免单次超时丢失进度。每条至少有标题、分类、来源、读取时间、正文和完整性标记，时长/画幅未注明就留空。保留原文与项目改写的区别；不通过自动付费翻译补全文，不执行外部仓库脚本。

优先处理电影叙事、运镜、人物表演、对白、参考图一致性及适用的动画案例；其他类别可保留研究索引，但不把它们整段送入模型。先校对上游许可和来源再保存适当原文；需要保留许可声明的原文随来源保存。只有实际读完且落盘的条目才能标“全文已归档”。

本次未建立完整案例JSON、未改Skill和运行时规则。后续实现、用户提供Skill的审查、新MiniMax文档接入和正式迁移状态，统一回写[主任务书](../implementation/quality-and-modularity-taskbook-2026-09-19.md)，不在此另排任务顺序。
