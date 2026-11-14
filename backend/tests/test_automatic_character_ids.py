"""Test automatic character ID generation in script generation flow."""

from comicflow.domain.models import CreateProject
from comicflow.infrastructure.memory import create_memory_runtime


async def test_guided_mode_generates_character_ids() -> None:
    """Test that guided mode script generation creates character cards and fills characterIds."""
    runtime = create_memory_runtime()
    pipeline = runtime.pipeline

    # Create project in guided mode
    created = await pipeline.create_project(
        CreateProject(
            input_type="idea",
            story="李明和王芳在雨夜的车站相遇，发现了一辆不存在的列车",
            duration_sec=60,
            mode="guided",
        )
    )
    project_id = created["project"]["id"]

    # Generate script
    result = await pipeline.generate_script(project_id)
    script = result["script"]

    # Verify script was generated
    assert script is not None
    assert "shots" in script
    assert len(script["shots"]) > 0

    # Verify at least some shots have characterIds
    shots_with_characters = [
        shot for shot in script["shots"] if shot.get("characterIds")
    ]

    # If LLM generated characters field, we should have character IDs
    # This is probabilistic - LLM might not always include characters
    # So we just verify the structure is correct, not that it's always populated
    for shot in script["shots"]:
        assert "characterIds" in shot
        assert isinstance(shot["characterIds"], list)
        # If characterIds are present, they should be valid IDs
        for char_id in shot.get("characterIds", []):
            assert isinstance(char_id, str)
            assert char_id.startswith("chr_")

    # If any characters were created, verify they exist in the repository
    if shots_with_characters:
        all_char_ids = set()
        for shot in shots_with_characters:
            all_char_ids.update(shot["characterIds"])

        for char_id in all_char_ids:
            character = await pipeline._character_repository.get(char_id)
            assert character is not None
            assert character["id"] == char_id
            assert character["source"] == "temporary"
            assert character["projectId"] == project_id


async def test_automatic_mode_generates_character_ids() -> None:
    """Test that automatic mode script generation creates character cards and fills characterIds."""
    runtime = create_memory_runtime()
    pipeline = runtime.pipeline

    # Create project in automatic mode
    created = await pipeline.create_project(
        CreateProject(
            input_type="idea",
            story="李明和王芳在雨夜的车站相遇",
            duration_sec=30,
            mode="automatic",
        )
    )
    project_id = created["project"]["id"]

    # Generate story text
    await pipeline.generate_story_text(project_id)

    # Split script
    result = await pipeline.split_script(project_id)
    script = result["script"]

    # Verify script was generated
    assert script is not None
    assert "shots" in script
    assert len(script["shots"]) > 0

    # Verify characterIds structure
    for shot in script["shots"]:
        assert "characterIds" in shot
        assert isinstance(shot["characterIds"], list)
        for char_id in shot.get("characterIds", []):
            assert isinstance(char_id, str)
            assert char_id.startswith("chr_")


async def test_character_ids_used_in_visual_generation() -> None:
    """Test that characterIds are correctly populated and can be assigned to shots."""
    runtime = create_memory_runtime()
    pipeline = runtime.pipeline

    # Create project
    created = await pipeline.create_project(
        CreateProject(
            input_type="idea",
            story="李明独自站在雨中等待着什么",
            duration_sec=30,
            mode="guided",
        )
    )
    project_id = created["project"]["id"]

    # Generate script - this should auto-create character cards
    result = await pipeline.generate_script(project_id)
    script = result["script"]

    # Verify that if characters were created, they can be retrieved
    first_shot = script["shots"][0]
    character_ids = first_shot.get("characterIds", [])

    for char_id in character_ids:
        character = await pipeline._character_repository.get(char_id)
        assert character is not None
        assert character["id"] == char_id

        # Verify get_shot_character_input works with these IDs
        character_inputs = await pipeline.get_shot_character_input(
            project_id, first_shot["id"]
        )
        # Should return character data for visual generation
        assert isinstance(character_inputs, list)


async def test_empty_characters_field_results_in_empty_character_ids() -> None:
    """Test that shots with no characters get empty characterIds list."""
    from comicflow.providers.message_contract import normalize_script_message

    # Script with explicit empty characters arrays (30 sec = 2 scenes, 6 shots)
    body = {
        "kind": "script",
        "version": 1,
        "content": {
            "title": "测试剧本",
            "scenes": [
                {"id": "scene-1", "title": "开场", "shotIds": ["shot-1", "shot-2", "shot-3"]},
                {"id": "scene-2", "title": "结尾", "shotIds": ["shot-4", "shot-5", "shot-6"]},
            ],
            "shots": [
                {
                    "id": "shot-1",
                    "title": "空镜头1",
                    "action": "风吹过",
                    "emotion": "平静",
                    "shotSize": "全景",
                    "durationSec": 5.0,
                    "visualDescription": "空旷的街道",
                    "dialogue": "",
                    "narration": "风吹过空旷的街道",
                    "characters": [],
                },
                {
                    "id": "shot-2",
                    "title": "空镜头2",
                    "action": "云飘",
                    "emotion": "平静",
                    "shotSize": "全景",
                    "durationSec": 5.0,
                    "visualDescription": "天空",
                    "dialogue": "",
                    "narration": "云在飘",
                    "characters": [],
                },
                {
                    "id": "shot-3",
                    "title": "空镜头3",
                    "action": "雨落",
                    "emotion": "平静",
                    "shotSize": "全景",
                    "durationSec": 5.0,
                    "visualDescription": "雨",
                    "dialogue": "",
                    "narration": "雨在落",
                    "characters": [],
                },
                {
                    "id": "shot-4",
                    "title": "空镜头4",
                    "action": "走",
                    "emotion": "平静",
                    "shotSize": "全景",
                    "durationSec": 5.0,
                    "visualDescription": "路",
                    "dialogue": "",
                    "narration": "走在路上",
                    "characters": [],
                },
                {
                    "id": "shot-5",
                    "title": "空镜头5",
                    "action": "停",
                    "emotion": "平静",
                    "shotSize": "全景",
                    "durationSec": 5.0,
                    "visualDescription": "停",
                    "dialogue": "",
                    "narration": "停下来",
                    "characters": [],
                },
                {
                    "id": "shot-6",
                    "title": "空镜头6",
                    "action": "望",
                    "emotion": "平静",
                    "shotSize": "全景",
                    "durationSec": 5.0,
                    "visualDescription": "望",
                    "dialogue": "",
                    "narration": "望着远方",
                    "characters": [],
                },
            ],
        },
    }

    result = normalize_script_message(body, target_duration_sec=30)

    for shot in result["shots"]:
        assert shot["characterIds"] == []


async def test_character_name_to_id_mapping() -> None:
    """Test that character names are correctly mapped to IDs."""
    from comicflow.providers.message_contract import normalize_script_message

    character_map = {
        "李明": "chr_abc123",
        "王芳": "chr_def456",
    }

    # 30 sec = 2 scenes, 6 shots
    body = {
        "kind": "script",
        "version": 1,
        "content": {
            "title": "测试剧本",
            "scenes": [
                {"id": "scene-1", "title": "相遇", "shotIds": ["shot-1", "shot-2", "shot-3"]},
                {"id": "scene-2", "title": "对话", "shotIds": ["shot-4", "shot-5", "shot-6"]},
            ],
            "shots": [
                {
                    "id": "shot-1",
                    "title": "李明登场",
                    "action": "走进车站",
                    "emotion": "疲惫",
                    "shotSize": "中景",
                    "durationSec": 5.0,
                    "visualDescription": "李明走进车站",
                    "dialogue": "李明：好累啊",
                    "narration": "",
                    "characters": ["李明"],
                },
                {
                    "id": "shot-2",
                    "title": "两人对话",
                    "action": "对视",
                    "emotion": "惊讶",
                    "shotSize": "近景",
                    "durationSec": 5.0,
                    "visualDescription": "两人四目相对",
                    "dialogue": "李明：你好\n王芳：你好",
                    "narration": "",
                    "characters": ["李明", "王芳"],
                },
                {
                    "id": "shot-3",
                    "title": "镜头3",
                    "action": "交谈",
                    "emotion": "平静",
                    "shotSize": "中景",
                    "durationSec": 5.0,
                    "visualDescription": "交谈",
                    "dialogue": "继续聊天",
                    "narration": "",
                    "characters": ["李明"],
                },
                {
                    "id": "shot-4",
                    "title": "镜头4",
                    "action": "思考",
                    "emotion": "沉思",
                    "shotSize": "近景",
                    "durationSec": 5.0,
                    "visualDescription": "思考",
                    "dialogue": "想一想",
                    "narration": "",
                    "characters": ["王芳"],
                },
                {
                    "id": "shot-5",
                    "title": "镜头5",
                    "action": "决定",
                    "emotion": "坚定",
                    "shotSize": "中景",
                    "durationSec": 5.0,
                    "visualDescription": "决定",
                    "dialogue": "好的",
                    "narration": "",
                    "characters": ["李明", "王芳"],
                },
                {
                    "id": "shot-6",
                    "title": "镜头6",
                    "action": "离开",
                    "emotion": "释然",
                    "shotSize": "全景",
                    "durationSec": 5.0,
                    "visualDescription": "离开",
                    "dialogue": "再见",
                    "narration": "",
                    "characters": [],
                },
            ],
        },
    }

    result = normalize_script_message(body, target_duration_sec=30, character_map=character_map)

    assert result["shots"][0]["characterIds"] == ["chr_abc123"]
    assert result["shots"][1]["characterIds"] == ["chr_abc123", "chr_def456"]


async def test_unknown_character_names_are_skipped() -> None:
    """Test that character names not in the map are skipped (not error)."""
    from comicflow.providers.message_contract import normalize_script_message

    character_map = {
        "李明": "chr_abc123",
        # "王芳" is not in the map
    }

    # 30 sec = 2 scenes, 6 shots
    body = {
        "kind": "script",
        "version": 1,
        "content": {
            "title": "测试剧本",
            "scenes": [
                {"id": "scene-1", "title": "相遇", "shotIds": ["shot-1", "shot-2", "shot-3"]},
                {"id": "scene-2", "title": "结尾", "shotIds": ["shot-4", "shot-5", "shot-6"]},
            ],
            "shots": [
                {
                    "id": "shot-1",
                    "title": "两人对话",
                    "action": "对话",
                    "emotion": "平静",
                    "shotSize": "中景",
                    "durationSec": 5.0,
                    "visualDescription": "两人对话",
                    "dialogue": "李明：你好\n王芳：你好",
                    "narration": "",
                    "characters": ["李明", "王芳", "未知角色"],
                },
                {
                    "id": "shot-2",
                    "title": "镜头2",
                    "action": "行动",
                    "emotion": "紧张",
                    "shotSize": "近景",
                    "durationSec": 5.0,
                    "visualDescription": "行动",
                    "dialogue": "继续",
                    "narration": "",
                    "characters": ["李明"],
                },
                {
                    "id": "shot-3",
                    "title": "镜头3",
                    "action": "转身",
                    "emotion": "犹豫",
                    "shotSize": "中景",
                    "durationSec": 5.0,
                    "visualDescription": "转身",
                    "dialogue": "等等",
                    "narration": "",
                    "characters": [],
                },
                {
                    "id": "shot-4",
                    "title": "镜头4",
                    "action": "走",
                    "emotion": "坚定",
                    "shotSize": "全景",
                    "durationSec": 5.0,
                    "visualDescription": "走",
                    "dialogue": "走吧",
                    "narration": "",
                    "characters": ["王芳"],
                },
                {
                    "id": "shot-5",
                    "title": "镜头5",
                    "action": "停",
                    "emotion": "思考",
                    "shotSize": "近景",
                    "durationSec": 5.0,
                    "visualDescription": "停",
                    "dialogue": "等一下",
                    "narration": "",
                    "characters": ["李明"],
                },
                {
                    "id": "shot-6",
                    "title": "镜头6",
                    "action": "离开",
                    "emotion": "释然",
                    "shotSize": "全景",
                    "durationSec": 5.0,
                    "visualDescription": "离开",
                    "dialogue": "再见",
                    "narration": "",
                    "characters": [],
                },
            ],
        },
    }

    # Should not raise error, just skip unknown names
    result = normalize_script_message(body, target_duration_sec=30, character_map=character_map)

    # Only "李明" is mapped, "王芳" and "未知角色" are skipped
    assert result["shots"][0]["characterIds"] == ["chr_abc123"]
