# 百炼中国内地图片／视频免费额度核验

核验日期：2026-09-09。依据阿里云官方公开文档；仅核验额度、期限、地域及超额处理，不作模型质量推荐。写入前已读工程规约、CONTEXT、相关 ADR、规格与实施计划。未调用生成 API、未读取密钥、未修改配置。

## 已确认额度与超额单价

下表均为官方计费页的**华北 2（北京）**条目。额度按图片张数或视频秒数赠送，不是现金余额；这是初始赠送数量，不代表当前账号仍有这些额度。[来源：模型调用计费](https://help.aliyun.com/zh/model-studio/model-pricing)

| 模型 ID | 新人免费额度 | 免费额度耗尽或过期后的按量单价 |
| --- | --- | --- |
| `wan2.2-t2i-flash` | 100 张 | 0.14 元／张 |
| `wanx2.1-t2i-turbo` | 500 张 | 0.14 元／张 |
| `wanx2.1-t2i-plus` | 500 张 | 0.20 元／张 |
| `wan2.2-i2v-flash` | 50 秒 | 480P：0.10 元／秒；720P：0.20 元／秒；1080P：0.48 元／秒 |
| `wanx2.1-i2v-turbo`（有 `x`） | 200 秒 | 480P、720P 均为 0.24 元／秒 |

- 主代理指定的 `wan2.2-i2v-flash` 480P／5 秒方案：50 秒相当于 10 段成功生成的 5 秒视频；额度耗尽后的完整 5 秒为 0.50 元。此为按官方秒数和单价计算，非额外赠送次数。[来源同上](https://help.aliyun.com/zh/model-studio/model-pricing)
- 名称差异：计费表的北京条目为 `wanx2.1-i2v-turbo`；无 `x` 的 `wan2.1-i2v-turbo` 列于新加坡条目，无当地免费额度。不能把北京的 200 秒直接归给无 `x` 名称；本次未核实无 `x` 名称能否作为北京别名调用。[来源同上](https://help.aliyun.com/zh/model-studio/model-pricing)
- 上述模型仅输出计费：图片按成功生成张数、视频按成功生成秒数计费；请求失败不产生费用，也不消耗免费额度。[图像计费规则](https://help.aliyun.com/zh/model-studio/model-pricing#26310bc5cf4do)、[视频计费规则](https://help.aliyun.com/zh/model-studio/model-pricing#d809366847gza)

## 有效期、地域和共享范围

- **仅北京地域享有免费额度**，不能拿北京赠送量抵扣新加坡等其他地域调用。[新人免费额度](https://help.aliyun.com/zh/model-studio/new-free-quota)
- **有效期通常为 90 天**，从开通百炼、模型发布、模型申请通过三个日期中较晚者起算。官方特别注明：2025-09-08 11:00 前已开通的用户，有效期可能不足 90 天。到期剩余量作废，不补发、不延期、不重置。[新人免费额度](https://help.aliyun.com/zh/model-studio/new-free-quota)
- 主账号与 RAM 子账号共享额度；不同模型的额度独立，不能合并或转移，某模型用尽不会自动切换其他模型。免费额度仅抵扣模型实时推理；不抵扣 Batch、模型调优／部署、OSS 存储及请求费用。[新人免费额度](https://help.aliyun.com/zh/model-studio/new-free-quota)

## 超额处理与“免费额度用完即停”

- **已实名认证账户默认关闭“用完即停”**；额度耗尽或过期后继续调用会转为按量付费，不应假定自然停服。未认证账户由系统强制开启，额度用完后不能继续调用。[新人免费额度](https://help.aliyun.com/zh/model-studio/new-free-quota)
- 可在电脑端控制台“免费额度”页按模型开启或批量开启，也可在模型详情页开启。开启后额度耗尽停止响应，返回 HTTP 403／`AllocationQuota.FreeTierOnly`，不会继续扣费。[新人免费额度](https://help.aliyun.com/zh/model-studio/new-free-quota)
- 必须提前设置：无免费额度、额度已耗尽或过期的模型无法开启；配置生效有延迟，变更尚未生效时继续调用仍可能收费。公开文档未明确说明视频剩余额度不足一整段时的跨额度任务处理，本次未作生成验证。[新人免费额度](https://help.aliyun.com/zh/model-studio/new-free-quota)

## 已核实的新模型条目与证据边界

官方北京计费表已列出 `wan2.7-image`（50 张，0.20 元／张）、`wan2.7-image-pro`（50 张，0.50 元／张）和 `wan2.7-i2v`（50 秒，720P 为 0.60 元／秒、1080P 为 1.00 元／秒），均标注上述 90 天规则。这里仅确认公开列名和额度，不确认当前账号已开通或可调用，不继续追查更新型号。[模型调用计费](https://help.aliyun.com/zh/model-studio/model-pricing)

本次未登录账户，**不能核实实际剩余额度、具体到期时间、调用权限和“用完即停”当前状态**；这些需以目标账号北京地域控制台为准。研究仅新增本文，不调整项目模型选择或工程决策。
