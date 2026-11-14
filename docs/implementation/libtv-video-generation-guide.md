# libtv 视频生成集成指南

## 概述

本文档提供 libtv 视频生成服务的调用流程和最佳实践，供 ComicFlow 项目参考和优化。

## 现状分析

### 当前实现

**文生图模式（已上线）**
- 使用 `wanx2.1-t2i-plus` 生成静态图片
- 位置：`backend/src/comicflow/providers/wanx_image.py`
- 流程：文本提示词 → 静态图片 → FFmpeg 拼接

**文生视频（已实现但未接入）**
- 使用 `wan2.2-t2v-plus` 生成动态视频
- 位置：`backend/src/comicflow/providers/video_synthesis.py`
- 状态：Provider 存在但未集成到 Pipeline

**图生视频原型（已实现但未测试）**
- 使用 `wan2.7-i2v` 生成首帧级联视频
- 位置：`backend/src/comicflow/providers/bailian_i2v.py`
- 状态：代码完整但 API 细节未验证

### Pipeline 集成点

**核心方法：** `ProductionPipeline.generate_shot_visual()` (`pipeline.py:870`)

```python
async def generate_shot_visual(
    self, project_id: str, shot_id: str, *, expected_version: int
) -> JsonObject:
    # 1. 获取镜头信息
    shot = self._require_shot(project, shot_id)
    
    # 2. 获取角色输入
    character_inputs = await self.get_shot_character_input(project_id, shot_id)
    
    # 3. 调用视觉 Provider（关键集成点）
    generated = await self._dynamic_visual_provider.generate(shot, character_inputs)
    
    # 4. 保存资产到项目
    assets = project.setdefault("visualAssets", [])
    asset = {**generated, "valid": True, "inputVersion": project["version"]}
    assets.append(asset)
```

**Provider 接口：** `DynamicVisualProvider.generate(shot, character_inputs)`

---

## libtv 视频生成 API 流程

### 方案 1：文生视频（Text-to-Video）

**适用场景：** 简单替换静态图片，不考虑镜头间连续性

#### API 调用流程

```python
# 1. 提交任务
POST https://dashscope.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis
Authorization: Bearer <BAILIAN_API_KEY>
X-DashScope-Async: enable

{
  "model": "wan2.2-t2v-plus",
  "input": {
    "prompt": "一个年轻女孩站在公园里，阳光明媚，竖屏构图，电影感光影"
  },
  "parameters": {
    "size": "1080*1920",        # 竖屏视频
    "duration": 5,              # 5 秒时长
    "prompt_extend": false,     # 禁止扩展提示词
    "watermark": false          # 无水印
  }
}

# 响应
{
  "output": {
    "task_id": "abc123xyz"
  }
}

# 2. 轮询任务状态
GET https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}
Authorization: Bearer <BAILIAN_API_KEY>

# 响应（进行中）
{
  "output": {
    "task_status": "PENDING"  # 或 "RUNNING"
  }
}

# 响应（完成）
{
  "output": {
    "task_status": "SUCCEEDED",
    "video_url": "https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/...",
    "results": [
      {"url": "https://..."}  # 备选字段
    ]
  }
}

# 3. 下载视频内容
GET <video_url>

# 4. 保存到 MinIO
PUT s3://comicflow/motion/{shot_id}.mp4
```

#### 参考实现

已实现：`backend/src/comicflow/providers/video_synthesis.py`

```python
class BailianVideoProvider:
    async def generate(self, prompt: str) -> JsonObject:
        # 1. 提交任务
        response = await client.post(_SUBMIT, json=payload)
        task_id = response.json()["output"]["task_id"]
        
        # 2. 轮询完成
        url = await self._poll(client, task_id)
        
        # 3. 下载视频
        video = await client.get(url)
        
        # 4. 保存到 S3
        object_key = f"motion/{os.urandom(4).hex()}.mp4"
        await self._asset_store.put_bytes(
            object_key=object_key,
            content=video.content,
            content_type="video/mp4",
        )
        
        return {
            "taskId": task_id,
            "objectKey": object_key,
            "durationSec": self._duration,
            "size": self._size,
            "provider": "wanx",
            "modelVersion": self._model,
            "sourceUrl": url,
            "bytes": len(video.content),
        }
```

#### 集成步骤

**Step 1: 配置环境变量**

```bash
# .env
VISUAL_PROVIDER_MODE=video  # 新增模式
BAILIAN_VIDEO_MODEL=wan2.2-t2v-plus
```

**Step 2: 修改 Provider 工厂**

```python
# backend/src/comicflow/infrastructure/providers.py

def create_visual_provider() -> DynamicVisualProvider:
    mode = os.getenv("VISUAL_PROVIDER_MODE", "real")
    
    if mode == "video":
        # 使用文生视频
        return BailianVideoProvider(
            api_key=os.getenv("BAILIAN_API_KEY"),
            model=os.getenv("BAILIAN_VIDEO_MODEL", "wan2.2-t2v-plus"),
            asset_store=create_asset_store(),
        )
    elif mode == "real":
        # 当前的文生图模式
        return BailianImageProvider(...)
    else:
        return MockVisualProvider()
```

**Step 3: 适配 Provider 接口**

```python
# BailianVideoProvider 需要适配 DynamicVisualProvider 接口

async def generate(self, shot: JsonObject, character_inputs: list[JsonObject]) -> JsonObject:
    # 1. 构建提示词
    prompt = self._build_prompt(shot, character_inputs)
    
    # 2. 调用原有的 generate(prompt) 方法
    asset = await self.generate(prompt)
    
    # 3. 添加 shotId
    asset["shotId"] = shot["id"]
    asset["id"] = f"vis_{uuid4().hex[:12]}"
    
    return asset

def _build_prompt(self, shot: JsonObject, character_inputs: list[JsonObject]) -> str:
    # 复用 wanx_image.py 的提示词构建逻辑
    parts = [shot.get("visual", "")]
    
    for char in character_inputs:
        parts.append(f"{char['appearance']}, {char['clothing']}")
    
    parts.append("竖屏构图，电影感光影，勿加文字水印")
    
    return ", ".join(filter(None, parts))
```

#### 注意事项

1. **轮询间隔**：视频生成耗时 2-5 分钟，建议 `poll_interval=6s`
2. **超时设置**：建议 `timeout=600s`（10 分钟）
3. **错误处理**：区分 `FAILED`、`CANCELED`、`TIMEOUT` 三种失败状态
4. **并发限制**：百炼 API 可能有并发限制，需要队列控制

---

### 方案 2：图生视频（Image-to-Video）

**适用场景：** 首帧级联，改善镜头间连续性

#### API 调用流程

```python
# 1. 提交任务
POST https://dashscope.aliyuncs.com/api/v1/services/aigc/video-generation/image-to-video
Authorization: Bearer <BAILIAN_API_KEY>

{
  "model": "wan2.7-i2v",
  "input": {
    "first_frame_image": "https://...",  # 首帧图片 URL（公网可访问）
    "prompt": "女孩微笑着挥手，镜头缓慢推进"
  },
  "parameters": {
    "size": "1080*1920",
    "duration": 5
  }
}

# 2-4. 后续流程同文生视频
```

#### 参考实现

已实现：`backend/src/comicflow/providers/bailian_i2v.py`

```python
class BailianImageToVideoProvider:
    async def generate_video(
        self,
        *,
        first_frame_url: str,
        prompt: str,
        reference_images: list[str] | None = None,  # 角色参考图（如果支持）
    ) -> str:
        payload = {
            "model": self._model,
            "input": {
                "first_frame_image": first_frame_url,
                "prompt": prompt,
            },
            "parameters": {
                "size": self._size,
                "duration": self._duration,
            },
        }
        
        # 提交 + 轮询 + 返回视频 URL
        ...
```

#### 首帧级联流程

```python
# Pipeline 中的镜头循环

previous_frame_url = None

for shot in shots:
    if previous_frame_url is None:
        # 第一个镜头：生成首帧图片
        first_frame = await image_provider.generate_image(...)
        first_frame_url = first_frame["url"]
    else:
        # 后续镜头：使用上一镜头的尾帧
        first_frame_url = previous_frame_url
    
    # 生成视频
    video_url = await i2v_provider.generate_video(
        first_frame_url=first_frame_url,
        prompt=shot["visual"],
    )
    
    # 下载视频并保存
    video_bytes = await download(video_url)
    object_key = await asset_store.put_bytes(video_bytes)
    
    # 提取尾帧用于下一镜头
    last_frame = await frame_extractor.extract_last_frame(video_bytes)
    previous_frame_url = await upload_to_public_url(last_frame)
```

#### 帧提取工具

已实现：`backend/src/comicflow/utils/frame_extractor.py`

```python
class FrameExtractor:
    async def extract_last_frame(self, video_bytes: bytes) -> bytes:
        # 使用 ffmpeg 提取尾帧
        # ffmpeg -sseof -1 -i input.mp4 -frames:v 1 output.jpg
        ...
```

#### API 验证需求

⚠️ **需要验证的问题：**

1. **端点是否存在？** `/services/aigc/video-generation/image-to-video`
2. **参数名称是否正确？** `first_frame_image` vs `image_url`
3. **是否支持 `reference_images`？** 用于角色一致性
4. **首帧 URL 要求？** 是否必须是公网可访问的 HTTP(S) URL
5. **模型名称？** `wan2.7-i2v` vs `happyhorse-1.1-i2v`

**验证方法：**

```bash
# 在容器内运行测试脚本
docker exec -it comicflow-backend bash
cd /app
python scripts/test_i2v_api.py       # 基础 API 验证
python scripts/test_i2v_e2e.py       # 端到端验证（图片 → 视频）
```

---

### 方案 3：角色参考图生视频（Reference-to-Video）

**适用场景：** 角色一致性优化（长期方案）

#### API 推测

```python
POST /services/aigc/video-generation/reference-to-video

{
  "model": "happyhorse-1.1-r2v",
  "input": {
    "prompt": "女孩在公园里散步",
    "reference_images": [
      "https://.../character-ref-1.jpg",
      "https://.../character-ref-2.jpg"
    ]
  },
  "parameters": {
    "size": "1080*1920",
    "duration": 5
  }
}
```

#### 实施步骤

1. **角色卡生成时创建参考图**

```python
async def create_character(...) -> JsonObject:
    character = {...}
    
    # 生成 1-2 张标准参考图
    ref_images = await self._generate_character_references(character)
    character["referenceImageUrls"] = ref_images
    
    return character

async def _generate_character_references(self, character: JsonObject) -> list[str]:
    prompt = f"{character['appearance']}, {character['clothing']}, 正面全身照，白色背景"
    
    image_1 = await image_provider.generate_image(prompt)
    image_2 = await image_provider.generate_image(prompt + ", 侧面")
    
    return [image_1["url"], image_2["url"]]
```

2. **剧本生成时产出 `characterIds`**

✅ 已完成（commit `05a3fc4`）

3. **视频生成时使用参考图**

```python
character_refs = []
for char_id in shot.get("characterIds", []):
    character = await character_repository.get(char_id)
    character_refs.extend(character.get("referenceImageUrls", []))

video_url = await r2v_provider.generate_video(
    prompt=shot["visual"],
    reference_images=character_refs[:9],  # 最多 9 张
)
```

---

## 推荐优化路径

### 阶段 1：快速切换到文生视频（1-2 天）

**目标：** 替换静态图片，生成真实动态视频

**步骤：**
1. 复用 `BailianVideoProvider`（已实现）
2. 适配 `DynamicVisualProvider` 接口
3. 环境变量切换 `VISUAL_PROVIDER_MODE=video`
4. 端到端测试

**成本评估：**
- 视频生成时间：2-5 分钟/镜头（vs 静态图 10-30 秒）
- API 成本：需要查询百炼定价

### 阶段 2：验证图生视频 API（1 天）

**目标：** 确认 i2v API 可用性和参数格式

**步骤：**
1. 运行 `scripts/test_i2v_api.py`
2. 运行 `scripts/test_i2v_e2e.py`
3. 记录验证结果（成功/失败/需要修改的参数）
4. 更新 `bailian_i2v.py` 中的 API 调用

### 阶段 3：实现首帧级联（2-3 天）

**目标：** 改善镜头间连续性

**步骤：**
1. 实现帧提取逻辑（`FrameExtractor`）
2. 修改 Pipeline 支持首帧传递
3. 错误处理和降级策略
4. 测试级联效果

### 阶段 4：等待 MiniMax 接入（后期）

**目标：** 终极视频一致性方案

**MiniMax H3 优势：**
- 原生支持 i2v 和 v2v
- 多角色参考图
- 同时生成立体声音频
- 2K 分辨率、15 秒时长

---

## 常见问题

### Q1: 为什么不直接使用现有的 `BailianVideoProvider`？

A: 该 Provider 已实现但：
- 未适配 `DynamicVisualProvider` 接口
- 未集成到 Pipeline 的 `generate_shot_visual` 流程
- 需要添加提示词构建逻辑（从镜头 + 角色生成 prompt）

### Q2: 视频生成太慢怎么办？

A: 优化策略：
1. **并行生成**：多镜头同时提交任务
2. **提前生成**：在剧本确认后立即开始
3. **增量生成**：用户修改镜头时只重新生成该镜头
4. **队列管理**：避免超过 API 并发限制

### Q3: 首帧级联失败怎么办？

A: 降级策略：
1. 单个镜头失败：重试 3 次
2. 连续失败：从该镜头开始回退到独立 t2v
3. 全局失败：整个项目回退到静态图模式

### Q4: 如何确保首帧 URL 可访问？

A: 百炼 API 要求首帧图片必须是公网可访问的 HTTP(S) URL，有两种方案：

1. **使用百炼生成的图片 URL**：
   - 文生图 API 返回的 `url` 是临时公网 URL
   - 有效期通常 24 小时
   
2. **上传到 MinIO 并配置公网访问**：
   - MinIO 配置 public bucket
   - 或使用预签名 URL（有效期可控）

### Q5: libtv 和百炼是什么关系？

A: 根据代码分析，当前没有发现 "libtv" 相关引用。推测：
- "libtv" 可能是用户自定义的术语
- 或者是计划接入的第三方视频生成服务
- 建议向用户确认 "libtv" 的具体含义

---

## 参考资源

### 已实现代码

- `backend/src/comicflow/providers/video_synthesis.py` - 文生视频 Provider
- `backend/src/comicflow/providers/bailian_i2v.py` - 图生视频 Provider
- `backend/src/comicflow/utils/frame_extractor.py` - 帧提取工具
- `scripts/test_i2v_api.py` - API 验证脚本
- `scripts/test_i2v_e2e.py` - 端到端测试脚本

### 文档

- `docs/implementation/video-consistency-plan.md` - 视频一致性完整方案
- `HANDOFF.md` - 项目交接文档

### 外部资源

- [百炼视频生成 API](https://help.aliyun.com/zh/model-studio/developer-reference/video-generation-api-example)
- [百炼图生视频文档](https://help.aliyun.com/zh/model-studio/image-to-video-first-and-last-frames-guide)

---

## 下一步行动

**立即可做：**
1. ✅ 阅读本文档
2. 🔲 决策：使用方案 1（文生视频）还是方案 2（图生视频）
3. 🔲 运行测试脚本验证 API（如果选方案 2）
4. 🔲 实施阶段 1：集成文生视频

**需要用户确认：**
- "libtv" 的具体含义和接入计划
- 视频生成成本预算
- 是否优先支持首帧级联
