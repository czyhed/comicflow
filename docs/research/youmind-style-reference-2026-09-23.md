# YouMind风格来源与取舍

访问日期：2026-09-23。用户指定[提示词库](https://youmind.com/zh-CN/prompts)。本记录保存来源和原创提炼，不是全部提示词归档或模型效果测试。

## 真人视频

首页“🔥 每周最热”明确写“过去七天最受关注的创意提示词精选”，图片与视频混排。以下五条当时均列于该栏，标记Seedance 2.5。这只证明YouMind当时的展示，不是独立热度测评、持续榜单订阅或H3兼容认证。

| 来源 | 阅读证据与取舍 | 项目应用 |
| --- | --- | --- |
| [灰色人群中红衣女子](https://youmind.com/zh-CN/video-prompts/crimson-coat-grey-crowd-video-10997)，[Iris原帖](https://x.com/xIrissy/status/2100511965840109644) | 已读YouMind详情译文：强调主体色彩对比、向外揭示环境。未独立读取原帖 | 新增电影色彩对比；保留用户服装颜色，不自动添加红衣、伞群、建筑或拉远镜头 |
| [周日上午邻里漫步](https://youmind.com/zh-CN/video-prompts/korean-sunday-neighborhood-walk-11085)，[作者原帖](https://x.com/AIwithkhan/status/2101515497150025999) | 已读YouMind详情译文：身份参考、日常动作、早期消费级DV质感、环境声音。原示例30秒、多事件、对焦/曝光变化；未独立读取原帖 | 新增真人纪实DV，只取自然肤质、轻微颗粒和克制手持；不套30秒、多事件、故意失焦、指定对白或无音乐要求 |
| [恐怖巴士袭击](https://youmind.com/zh-CN/video-prompts/horror-bus-attack-prompt-11175) | 首页与页面摘要，巴士空间内动作恐怖；未逐句归档全文 | 与下两例合并提炼克制悬疑摄影，只取真实空间、光影和反应节奏 |
| [卧铺火车僵尸感染](https://youmind.com/zh-CN/video-prompts/sleeper-train-zombie-video-11024) | 首页与页面摘要，受限空间、写实效果；未逐句归档全文 | 不把僵尸、感染、攻击或血腥内容注入普通故事 |
| [韩国公寓恐怖场景](https://youmind.com/zh-CN/video-prompts/korean-apartment-horror-video-11022) | 首页与页面摘要，电梯/走廊的空间压迫感；未逐句归档全文 | 不把白天改为黑夜；五官、路径和动作接触点保持可辨 |

风格仅表达视觉，不决定故事类型。三个新增ID：`documentary-dv`、`suspense-realism`、`cinematic-color-contrast`。原六预设v2保持；新ID也使用现有v2规则结构。DV的手持规则放在motion，角色参考图不追加视频抖动/失焦要求。尚未生成样片，不承诺当前H3可复现社区成片。

## Image 2与2.5

已读取[Image 2目录](https://youmind.com/zh-CN/gpt-image-2-prompts)和[Image 2.5目录](https://youmind.com/zh-CN/gpt-image-2-5-prompts)的热门列表、可见摘要和说明。目录中的模型名称为YouMind分类，不据此推断本项目同名代理模型的实际来源、能力、参数或官方身份。没有调用网站生成按钮。

- Image 2可见示例包括晨间厨房、青蓝背光人像、怀旧剪贴簿和纸艺海报。共同可取的是明确主体、媒介、构图、材质和光源。原例中的固定人物、配色、85mm/f1.8、8K、拼贴版式等不作为通用角色板要求。
- Image 2.5可见示例包括真实随拍、角色设定图、编辑风格角色参考表、唐代CG肖像和铅笔画。页面明确说明该合集同时包含作者公开提示词和AI根据图片反推的描述，不能把所有条目都说成作者原稿。
- 保留已验证的脸部＋正侧背整板布局，不把示例中的多表情、动态姿势、多套服装整批加入身份参考。不同观察角度不能改变人物身份、衣着和比例。
- 本项目实际发现：`OpenAIImageProvider._build_prompt`在已编译的主图文字后仍追加强制3D、真实毛孔、8K和UE5等词，与二维、绘画或真人摄影规则冲突。移除此固定段，改为遵守既有画风及人物信息。接口、用途绑定、模型ID和生成次数保持；不为两个名称建立未经证实的能力分支。

本批按既有风格结构与适配器修正，不安装网页Skill、不执行网页脚本、不复制社区图片进入产品。目录色彩示意为CSS绘制，明确标示为示意，不能当作模型输出预览。
