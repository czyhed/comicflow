#!/bin/bash
# ComicFlow 完整流程测试脚本

set -e

API_BASE="http://127.0.0.1:18000/api"
PROJECT_ID=""

echo "🚀 开始测试完整流程..."

# 1. 创建项目
echo "📝 Step 1: 创建项目"
RESPONSE=$(curl -s -X POST "$API_BASE/projects" \
  -H "Content-Type: application/json" \
  -d '{
    "inputType": "story",
    "story": "一个年轻的程序员在深夜调试代码时，发现屏幕上出现了一个神秘的对话框，里面的AI开始和他对话，告诉他一个改变世界的秘密。他必须在天亮前做出选择：是继续平凡的生活，还是踏上未知的冒险旅程。",
    "durationSec": 60,
    "mode": "automatic"
  }')

PROJECT_ID=$(echo $RESPONSE | jq -r '.project.id')
echo "✅ 项目创建成功: $PROJECT_ID"

# 2. 生成故事文本
echo "📖 Step 2: 生成故事扩展"
curl -s -X POST "$API_BASE/projects/$PROJECT_ID/story" | jq '.project.stage'

sleep 3

# 3. 拆分剧本
echo "📋 Step 3: 拆分剧本"
curl -s -X POST "$API_BASE/projects/$PROJECT_ID/script/split" | jq '.script.title'

sleep 2

# 4. 确认剧本
echo "✓ Step 4: 确认剧本"
VERSION=$(curl -s "$API_BASE/projects/$PROJECT_ID" | jq '.project.version')
curl -s -X POST "$API_BASE/projects/$PROJECT_ID/script/confirm" \
  -H "Content-Type: application/json" \
  -d "{\"expectedVersion\": $VERSION}" | jq '.project.stage'

# 5. 启动自动生成会话
echo "🎬 Step 5: 启动自动生成"
curl -s -X POST "$API_BASE/projects/$PROJECT_ID/generation-session/advance" | jq '.status'

# 6. 监控生成进度
echo "⏳ Step 6: 等待生成完成..."
# 设上限，否则流水线卡住时脚本会永久挂着，看起来像"还在跑"
DEADLINE=$(( $(date +%s) + 900 ))
while true; do
  STAGE=$(curl -s "$API_BASE/projects/$PROJECT_ID" | jq -r '.project.stage')
  echo "当前阶段: $STAGE"

  if [ "$STAGE" = "exported" ]; then
    echo "✅ 生成完成！"
    break
  elif [[ "$STAGE" == *"failed"* ]]; then
    echo "❌ 生成失败: $STAGE"
    exit 1
  elif [ "$(date +%s)" -ge "$DEADLINE" ]; then
    echo "❌ 超过 15 分钟仍停在 $STAGE，判定卡住"
    echo "   排查: docker compose logs --tail=100 api worker"
    exit 1
  fi

  sleep 5
done

# 7. 获取导出结果
echo "📦 Step 7: 获取导出文件"
curl -s "$API_BASE/projects/$PROJECT_ID/export" | jq '.downloads'

echo "🎉 完整流程测试成功！"
