# 仙宫云 H3 本机运行更新

2026-09-23：用户明确「执行吧，还有分辨率应该可以自选吧」，授权更新本机运行环境及已有模型配置。本机更新已完成；仙宫云应用就绪检查返回503，真实生成仍未验证。

## 实际运行环境

临操作发现18002端口归属 `local-runtime-api-1`，不是旧 `comicflow-local-validation-api-1`。当前私有Compose是 `var/verification/ui-validation-20260921/local-runtime/compose.json`、项目名 `local-runtime`。API源码只读挂载本仓库；原Worker/Beat均未运行。

重启前核对API与Compose的API/Worker/Beat使用相同数据库、MinIO、Redis命名空间和原解密密钥文件，不输出凭据。沿用命名空间 `comicflow-local-validation-20260921` 和原密钥卷；没有迁移或切换数据服务。

已重启 `local-runtime-api-1`，通过既有Compose仅启动 `worker beat`，没有启动 migrate 或旧项目消费者。API健康正常，Worker `inspect ping`返回1节点pong，前端5173代理能读取新协议和revision40。

## 模型及任务记录

已有模型「仙宫云minimax」原本使用 `compshare-h3`，模型ID为「仙宫云Minimax」，分辨率768P。现更新同一模型为 `xiangongyun-h3` / `MiniMax-H3`，默认0.5P、平衡档、context-ir，配置版本39→40。模型ID记录、视频用途引用、连接记录和已保存密钥均保留；未新增重复模型或连接，未改文本/图片用途。

重启前发现1笔旧排队视频：`vjob_21994c65f99c4ec0bf356e75c6772c68`，属于 `prj_f9f6e04d5dd7` / `s1`，revision39，attempts=0、taskId为空、文本/视频调用均0。为避免开启调度器后把旧协议任务自动提交，先保存原记录，再经 `SqlVideoJobStore.change` 使用条件校验和乐观锁将其记为failed / `VIDEO_JOB_CONFIG_CHANGED`，原因 `protocol_changed_before_submission`，保留历史、原输入、原配置版本，释放该镜头的活跃槽位。没有删除记录或取消任何远端任务。

启动后的outbox由148 published/1 pending变为149 published；旧事件被消费时终态任务不执行Provider。复核该任务attempts仍0、taskId仍空、调用仍0。4笔成功视频、3笔成功图片/2笔已取消图片、154个项目数量保持原样。用户下一次点击会建立新协议下的新操作。

本机私有备份与检查输出在 `var/verification/xiangongyun-runtime-20260923/`：`catalog-before.json`、`catalog-after.json`、`queued-job-before.json`、`preflight-after.json`、`runtime-after.json`。模型目录回读只含配置状态，不含明文密钥；文件不提交Git。

## 分辨率与验证

主模型库增加「仙宫云分辨率」「仙宫云推理档位」下拉框，与调用JSON双向同步；保存模型后生效。无效JSON保持原文并禁用选择，不覆盖其他参数。在途任务保留原配置。

| 档位 | 竖屏像素 |
| --- | --- |
| 0.4P | 480×832 |
| 0.5P（当前） | 544×960 |
| 0.6P | 576×1024 |
| 0.7P | 640×1120 |
| 0.8P | 672×1216 |
| 0.9P | 704×1280 |
| 1.0P | 768×1344 |

横屏交换宽高。分辨率档位来自用户API文档，本批未以真实生成确认像素、耗时或费用。

真实项目《末班车》s1只读准备单通过：`xiangongyun-h3`、revision40、6秒、ref2va、2参考图、0.5P/544×960/9:16、文本0/视频1、compilePrompt=false、platformOptimization=false。此结果证明本机路由和素材准备条件，不是成片验证。

前端build通过；模型库及准备单6项Playwright模拟测试通过，覆盖选择0.8P与质量档后同步JSON、保存不调用生成。该UI增量没有改后端逻辑；后端920通过/3跳过、Ruff/Mypy94等沿用[上一批验收](xiangongyun-h3-integration-2026-09-23.md)，未重复全量运行。

## 当前远端限制

只读调用仙宫云 `/api/v1/ready`（Bearer）和 `/api/config`（无鉴权），均为HTTP503、text/plain、非JSON，尚不能判断是实例未启动、路由不可用还是应用启动未完成；不能声称GPU已就绪。没有调用 `/api/v1/jobs` 提交生成，也没有实例部署/开关机操作。

下一步由用户确认实例在线并等待应用就绪；就绪后刷新网页与镜头准备单，用户点击生成验证。若503持续，先检查当前连接是否仍对应实例最新web_url，避免用重复生成排查。

数据库、MinIO、原模型解密密钥正式迁移和Redis干净命名空间/单写端切换仍保留，7C暂停。本批是用户授权的本机运行更新，不是服务器发布。
