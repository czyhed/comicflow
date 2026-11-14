# 百炼图片与视频模型：流程测试推荐

> 后续实施更新：用户要求配置可切换测试/正式用途后，百炼视频 Adapter、配置选项和双配置切换已接入，见 `../implementation/provider-profile-switching.md`。下文原型缺陷是本次修改前的调研记录；未进行真实收费验证。

查询日期：2026-09-09。目标是先用账号可用的试用额度验证流程；本轮仅查官方文档和本地代码，未调用生成 API、未修改配置。

## 推荐组合

| 用途 | 首选 | 最小测试参数 | 理由 |
| --- | --- | --- | --- |
| 角色、场景静态参考图 | `wan2.2-t2i-flash` | `n=1`，`720*1280` | 官方极速版，沿用项目现有异步文生图协议；2.2 模型宽高均可在 512–1440 范围内 |
| 先跑图生视频/下载/合成 | `wan2.2-i2v-flash` | `resolution=480P`，5 秒，一张首帧图 | 官方支持 480P/720P/1080P，固定 5 秒；适合作为最小流程样本 |
| 保持当前图片模型 | `wanx2.1-t2i-plus` | `n=1` | 已有配置，若账号对此模型还有额度，无需为测试而换模型 |
| 需要更短的视频样本 | `wanx2.1-i2v-turbo` | 480P，3 秒 | 官方支持 3/4/5 秒，适合按生成秒数控制测试消耗；须核对该模型剩余额度 |

这是工程接入与测试成本建议，不是实测画质排名。免费额度取决于账号、地域、模型及有效期，不能从模型名字推定免费。额度规则另见 `bailian-free-quota-notes.md`。

## 与项目的兼容情况

图片 Adapter `backend/src/comicflow/providers/wanx_image.py` 已使用文生图异步接口、`X-DashScope-Async: enable`、`input.prompt`、`parameters.size/n`，与官方 2.2 示例协议吻合；可以在图片管理页更换支持该协议的模型，仍需账号服务实际核验。

视频管理工厂 `providers/media_config.py` 当前仅接受 `compshare-h3`，没有百炼视频选项。`bailian_i2v.py` 只是未接入主链路的原型，不能将存在这个文件视为已支持万相视频。与本次官方文档相比：

- 原型路径是 `/services/aigc/video-generation/image-to-video`，官方是 `/services/aigc/video-generation/video-synthesis`。
- 原型首帧字段是 `first_frame_image`，官方是 `input.img_url`。
- 原型使用 `size`，官方图生视频选择 `parameters.resolution`，纵横比参考首帧图。
- 原型没有必需的 `X-DashScope-Async: enable`。
- 原型默认 `wan2.7-i2v` 未在本次图生视频文档中找到，不能作为可用模型依据。
- 原型返回 URL，尚未实现主流水线所需的统一 `generate(shot, characters)` 视频资产、下载/对象存储和尾帧消费契约。

不能只改 H3 配置里的模型名或地址。下一步若选用百炼，需要加入独立视频 Adapter/配置选项，按官方契约实现提交、轮询、下载和资产持久化，再以 MockTransport 和现有流程门禁验证。

## 测试顺序

1. 在百炼控制台核对目标地域对应模型的剩余额度、有效期及免费额度用完即停设置。
2. 优先复用现成图片作为首帧，只生成一段 480P、5 秒样本，验证提交/轮询/下载/保存/播放。
3. 图生视频首帧应是完整镜头画面。单独的角色白底图只适合测角色运动，不能自动证明角色与场景已融合；先制作人物在目标场景中的关键帧，再测试场景镜头。
4. 单段通过后，再测试两个镜头的尾帧提取、下一镜头输入和 FFmpeg 合成。既有 11 项离线回归应先修复，不直接点全自动批量生成。
5. 基础图生视频只消费一张首帧，不等同于 H3 多参考人物模式。H3 的三/六节、Picture/Subject 标签和声音段不能直接当成万相接口约定；切换供应商需专门提示词编译，保留既有 H3 Skill 路径。

## 官方来源

- [万相文生图 API](https://help.aliyun.com/zh/model-studio/text-to-image-v2-api-reference)：模型名、异步协议、尺寸、按张生成。
- [万相图生视频 API](https://help.aliyun.com/zh/model-studio/image-to-video-api-reference)：模型名、分辨率、时长、首帧字段、异步请求头、任务查询。

官方目前推荐使用业务空间专属域名；北京、新加坡等地域密钥与域名不可混用。本项目现有中国内地配置使用 `https://dashscope.aliyuncs.com/api/v1`，本次不改动用户配置。
