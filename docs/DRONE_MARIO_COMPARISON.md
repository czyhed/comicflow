# Mario 成功部署样例与 ComicFlow 对比

日期：2026-09-17。

参考目录：用户提供的 `D:/WeChat/liaotianjilu/xwechat_files/wxid_20lqwkweqo7l12_66d0/msg/file/2026-09/mario_app/`。
仅阅读 `.drone.yml`、`compose.yml`、`Dockerfile`、README 和忽略规则，没有运行该项目或改动其文件。
用户说明该项目部署成功；本次没有独立核验其线上容器。

## 已确认差异

| 项目 | Mario | ComicFlow |
| --- | --- | --- |
| 构建触发 | `event: [push]` 且 `branch: [main]` | `event: [tag]` |
| 部署执行器镜像 | `docker:28-cli` | 相同 |
| Docker 连接 | 宿主 `/var/run/docker.sock` | 相同 |
| 镜像版本 | `APP_VERSION: ${DRONE_COMMIT_SHA}` | 相同 |
| 更新方式 | Compose build，然后 up --no-build --wait | 相同基础方式，后端增加基础设施、建桶和迁移顺序 |
| 并发 | 1 | 1 |
| Compose 项目 | `mario-app` | `comicflow-backend` / `comicflow-web` |
| 宿主端口 | 8080 | 前端18080，后端服务不发布宿主端口 |
| 应用与配置 | 静态文件，无数据库配置 | API、Worker、Beat、PostgreSQL、Redis、MinIO；需要 `backend_env` |

Mario 的 `APP_VERSION` 是 Docker 镜像标签，不代表流水线由 Git 标签触发。
现有成功样例只能支持比较部署模式，不能证明 ComicFlow 的 webhook 订阅相同。
ComicFlow 此前两次 main push 曾创建构建，后续构建分别在镜像拉取和仓库克隆阶段失败。
当前标签未出现新构建发生在构建步骤之前，改 Dockerfile 或删除检查步骤不能解决事件触发问题。

## 按样例实施的具体方案（用户已确认）

用户已明确同意普通 main push 自动部署，两份发布流水线的 trigger 改为：

```yaml
trigger:
  event: [push]
  branch: [main]
```

不同时开启 tag 触发，避免同次版本的分支和标签推送创建两次部署。
Git 版本标签继续保留作回溯标记，Docker 镜像继续使用完整提交 SHA。
该确认覆盖先前“只由标签触发”的要求，现已授权修改配置并推送部署。

实施范围：根工作区 `.drone.yml`、`deploy/drone.web.yml`、前后端发布 README、部署文档、工程决策及干净发布克隆中的对应文件。
保留现有阻断检查、克隆重试、Secret、数据库迁移顺序、独立网络/项目名以及18080端口。
不复制 Mario 的8080端口或容器项目名，不迁移本地数据，不调用模型。

验证与发布顺序：

1. 校验两份 YAML 的 push/main 触发和现有测试、Secret、socket挂载未改变；检查文档一致性。
2. 仅从干净后端发布克隆提交并推送 main，同时保留版本标签；观察是否出现新 Drone 构建。
3. 若仍无构建，继续核查 webhook/Drone 日志，不能宣称分支触发已经修复。
4. 后端构建、迁移及健康通过后才发布前端；验证18080首页、API代理和健康接口。
5. 更新 HANDOFF、验证记录和任务状态。构建开始、构建成功、上线健康分别记录。

历史标签未触发的根因仍未确认；恢复 main/push 不等于修复 GitHub create 事件订阅。
