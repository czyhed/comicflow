# H3 社区资料归档与可用证据

读取日期：2026-09-22。执行原任务书第 3.1 节的资料落盘；没有调用模型、执行外部脚本、下载图片或视频、修改业务数据或部署。项目改写规则与来源正文分开。

## 实际覆盖

本次完整解析 xianyu 上游 Gallery 的 **222 条记录**，保存其中 **72 条明确以 MIT 发布的重建提示词全文**；另外 **150 条作者原写提示词只保存索引，未保存全文**。ZeroLu 保存上游 JSON 的 **8 条记录，其中 7 条有公开正文、1 条缺失**。因此有正文的记录共 79 条，但不能将其写成“79 条作者原稿”，也不能声称 tryminimax 的 222 条全文全部完成。

| 来源 | 本次实际读取 | 本地文件与完整性 |
| --- | --- | --- |
| [tryminimax 中文提示词页](https://tryminimax.asia/zh/minimax-h3-prompts) | HTTP 200；页面显示 222 条及十类计数；服务端 HTML 实际含 24 个提示词卡片 ID | [页面核验信息](data/h3-community-2026-09-22/source-evidence.json)保存 URL、读取时间、字节数及 SHA-256；没有把首页 24 张卡当作全站全文 |
| [xianyu Gallery](https://github.com/xianyu110/awesome-minimax-h3-prompts/blob/main/prompts/GALLERY.md) | 完整读取 340,617 字节，解析 222 个唯一 ID，72 个完整正文代码块 | [222 项归档](data/h3-community-2026-09-22/xianyu-gallery-entries.json)逐项包含标题、分类、作者、原帖、网页锚点、读取时间、正文/空值、时长/画幅元数据和完整性；150 条未授权原文的 `body` 为 `null` |
| [ZeroLu 案例 JSON](https://github.com/ZeroLu/awesome-minimax-h3/blob/main/data/community-x-minimax-h3-cases.json) | 完整读取 26,621 字节，8 项，7 complete / 1 missing | [原始文件](data/h3-community-2026-09-22/zerolu-upstream.json)保持上游字节；[逐项记录](data/h3-community-2026-09-22/zerolu-entries.json)补本次读取时间、来源与完整性。`x-mm-h3-04` 正文仍为空 |

“完整”只表示对应上游公开文本/代码块完整传输并保存，不证明原作者生成输入、参考图片、参数或完整工作流都已公开，也不证明案例可复现。所有条目均经程序提取和结构检查；下文所列案例另外阅读正文提炼。没有人工逐点打开网页全部 222 个“展开全文”，也未逐一重访 X 原帖或播放样片。

### 分类计数

| Gallery 分类 | 实际解析数 |
| --- | ---: |
| Cinematic & Story | 43 |
| Animation & Anime | 45 |
| Ads & Products | 52 |
| Character & Performance | 23 |
| VFX & Transitions | 21 |
| Camera Motion | 11 |
| Reference & Consistency | 9 |
| Video Editing | 7 |
| Dialogue & Sound | 8 |
| Animals | 3 |
| 合计 | 222 |

网页计数、上游 Gallery 和既有来源登记一致。xianyu README 某个徽章写 224，而正文及 Gallery 仍是 222；归档采用实际解析数，不将徽章当作覆盖证据。

## 许可与来源边界

[xianyu README](https://github.com/xianyu110/awesome-minimax-h3-prompts/blob/main/README.md)明确区分两类：150 条作者原稿仅索引，说明其不拥有原稿；72 条是根据样片重建的提示词，明确标 MIT。故 MIT 不能外推覆盖网页中的 150 条作者全文。本次只对 72 条重建提示词保存全文，保留 [xianyu MIT 许可全文](data/h3-community-2026-09-22/xianyu-LICENSE.txt)，署名为 `Copyright (c) 2026 API Models (tryminimax.asia)`。原视频作者及原帖链接依旧逐项保存，但不能把视频作者标成重建文本作者。

[ZeroLu LICENSE](https://github.com/ZeroLu/awesome-minimax-h3/blob/main/LICENSE)为 MIT，署名 `Copyright (c) 2026 ZeroLu`，已随[原始声明](data/h3-community-2026-09-22/zerolu-LICENSE.txt)保存。README 说明案例来自公开 X 帖子及公开镜像；本次依仓库公开 MIT 声明归档其已发布 JSON，保留逐条原作者和链接。尚未独立核实每位原作者的单独授权，规范化记录显式保存该限制；不由仓库许可推导视频、肖像、角色 IP 或其它第三方材料的商用授权。

未完成的 150 条保持 `index-only-author-permission-unverified`，未补写、机器重建或付费翻译。用户要求的 222 条网页全文因此仍有明确缺口。现有 72 条 reconstructed 也不能回填为这 150 条的作者原文。

## 对现有规则的具体增量

既有[来源登记](h3-prompt-source-register-2026-09-22.md)和中文 H3 编译已覆盖素材职责、动作时间线、逐字对白、旁白、声音及风格约束。本次不是发现必须新建的提示词框架；主要增量是可追溯的正文、许可和反例，以及下列更具体的判断依据。

| 已阅读案例及定位 | 正文可支持的判断 | ComicFlow 应用边界 |
| --- | --- | --- |
| [Dynamic Urban Parkour Flow](https://tryminimax.asia/zh/minimax-h3-prompts#prompt-cmsb63ita000404jx0qlnqhwk)，MIT 重建 | 动作按障碍物、落点、落地姿态和后续翻滚展开；镜头方向让位移可辨 | 在原稿确实要求接触/位移时加强可见过程和结束状态；不把所有普通镜头改成跑酷、快切或 15 秒 |
| [Echoes of a Midnight Call](https://tryminimax.asia/zh/minimax-h3-prompts#prompt-cmsb20gvh00090bkyii6lyszi)，MIT 重建 | 电话对话中的倾听和闭眼反应属于表演，静机与近景可以承载情绪 | 保留原稿的停顿和静止，不用“持续动作”规则强迫倾听者运动；不能从重建文中的泛称 dialogue 补造对白 |
| [ZeroLu-08](https://x.com/TechieBySA/status/2084600512180113820)，仓库公开正文 | 凝视、停顿、听后反应和最后一句后的留白均有独立指示 | 保留原稿已有的反应，不推断新的台词或机械增设每句停顿；时长仍按真实镜头预算 |
| [ZeroLu-02](https://x.com/aiwithaly/status/2087102541146522089)，仓库公开正文 | 注意对象→取景→拍照→展示照片→说话→继续行走，动作有因果链 | 需要检查手、相机、照片的可见关系；不能默认短镜头能容纳完整六步 |
| [Curious Clay Sheep's Adventure](https://tryminimax.asia/zh/minimax-h3-prompts#prompt-cmsb3u6is000004l5fguhkucz)与[Felt Anglerfish Ocean Adventure](https://tryminimax.asia/zh/minimax-h3-prompts#prompt-cmsb5cguz000a04l1natgsc4q)，MIT 重建 | 黏土/羊毛毡的表面、边缘及动作质感分别描述；明确排除不相容的写实或 CGI 质感 | 支持按媒介写具体材质，不能把这些新媒介自动加成第七、第八种预设，或塞入现有六预设 |
| [Echoes of the Neon City](https://tryminimax.asia/zh/minimax-h3-prompts#prompt-cmsb63m6z000b04jxqqhpvm2c)，MIT 重建 | 2D 媒介与赛博朋克题材分开表达，色光和环境反射服务具体场景 | 支持“媒介/题材分开”的既有决定；并不支持给所有动漫镜头添加霓虹、湿地反射或额外文字 |

这些都是写作证据，尚无本项目付费 A/B 画质证据。示例里的 15 秒、16:9/21:9、命名角色、配乐、品牌、转场和镜头数不能覆盖当前项目事实、低成本档位或参考图编号。程序读取研究文件不会成为新生成路径；运行请求只使用经项目规则取舍的必要内容。

## 校验与可追溯性

[获取清单](data/h3-community-2026-09-22/acquisition-manifest.json)记录源 API URL、不可变 Git blob URL、Git blob SHA、SHA-256、字节数和 UTC 读取时间。对四份原始响应解码结果按 Git 的 `blob <length>\0<bytes>` 算法核对 SHA-1；Gallery 同时核验 222 个唯一 ID、十类计数与 72 个完整正文块。ZeroLu 原始 JSON 字节保留，规范化记录与上游正文逐项比对。零媒体文件下载，外部仓库脚本未执行。

规范化条目的 `durationSeconds` 和 `aspectRatio` 只来自显式结构元数据；ZeroLu 没有单独提供这两个字段，因此保留 `null`，正文中出现的时间段依旧原样保存，不把归档字段空值误解成原文没有时间描述。`x-mm-h3-04` 的原始文件包含一条“提示词不可用”的占位说明，规范化记录将其放入 `upstreamPlaceholder`，`body` 为 `null`，不把说明当作第八条提示词。所有正文保持原语言；中文标题不代表提示词已翻译。

本文件及数据只完成资料分支。主任务书中的只读项目盘点、有限规则优化与验收由对应执行记录说明；PostgreSQL、MinIO、原模型解密密钥迁移和 Redis 干净命名空间切换继续保留，未在本次执行。
