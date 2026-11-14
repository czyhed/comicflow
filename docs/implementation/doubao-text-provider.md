# 火山方舟 Doubao 文本 Provider

状态：已接入，等待用户配置 API Key 后做最小文本验证

## 接入范围

ComicFlow 已新增 `DoubaoTextProvider`，通过火山方舟的 OpenAI 兼容接口调用：

```text
POST https://ark.cn-beijing.volces.com/api/v3/chat/completions
Authorization: Bearer <DOUBAO_API_KEY>
```

默认模型名称为 `Doubao-Seed-2.1-turbo`。如果火山方舟控制台为你的模型分配了 Endpoint ID，应在“模型名称”中填写 `ep-...` 接入点 ID；模型名称和 Endpoint ID 由用户自行配置，不在代码中锁定。

豆包可以用于：

- 中文故事生成；
- 中文剧本拆分和润色；
- 角色提示词助手；
- MiniMax H3 视频生成前的 H3 Skill Prompt 扩写。

H3 视频仍由 MiniMax H3 生成。豆包只负责文本理解和 Prompt 扩写，不会替代 H3 视频 Provider。

## 在哪里填写 API Key

推荐使用网页控制台：

1. 启动项目并打开前端。
2. 打开“模型 API 配置”。
3. 在“文本 / 剧本 API”中选择“正式配置”或“测试配置”。
4. 供应商选择“火山方舟 / Doubao”。
5. API 地址保持 `https://ark.cn-beijing.volces.com/api/v3`。
6. API Key 填写火山方舟控制台创建的 Key。
7. 模型名称填写 `Doubao-Seed-2.1-turbo` 或你的 `ep-...` Endpoint ID。
8. 勾选“启用文本 API”，点击“保存文本配置”。
9. 需要切换测试/正式配置时，先保存，再点击对应配置的切换按钮。

保存和切换配置不会调用模型。当前配置只保存在 API 进程内，重启 API 后需要重新在页面填写，除非同时配置下面的 `.env` 环境变量。

## 使用 `.env` 配置

在项目根目录 `.env` 中填写：

```dotenv
PROVIDER_MODE=real
PROVIDER_EVALUATION_GATE=passed
TEXT_PROVIDER_PROVIDER=doubao
DOUBAO_API_KEY=你的火山方舟APIKey
DOUBAO_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
TEXT_PROVIDER_MODEL=Doubao-Seed-2.1-turbo
```

如果使用 Endpoint ID：

```dotenv
TEXT_PROVIDER_MODEL=ep-xxxxxxxxxxxxxxxx
```

不要把真实 Key 写入 `.env.example`、Git 提交、前端代码或截图。Docker 启动时 API、Worker 和 Beat 会读取这些变量。

## 额度安全验证顺序

1. 保存配置，不点击任何故事、角色或视频生成按钮。
2. 只使用文本配置的连通性检查，确认地址、Key 和模型可访问。
3. 先对一个已保存的小段文本做 Prompt 扩写验证。
4. 检查 H3 Skill 输出是否通过结构、语言、角色标签、图片引用和对白校验。
5. 文本验证通过后，才授权一次最小视频镜头测试。

文本验证仍可能消耗豆包额度；这一步不会消耗 MiniMax 视频额度。视频生成不会自动重试。

## 离线验证

新增 `backend/tests/test_doubao_text.py`，验证默认地址、Bearer 鉴权、标准 Chat Completions 返回结构、控制台配置构造了真实豆包 Adapter，以及环境变量选择逻辑。测试使用 `httpx.MockTransport`，不连接火山方舟，不调用任何供应商 API。
