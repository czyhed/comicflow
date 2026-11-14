from __future__ import annotations

from uuid import uuid4

from comicflow.domain.models import JsonObject


class MockModerationProvider:
    async def moderate(self, text: str) -> JsonObject:
        blocked_terms = ("暴恐", "诈骗", "自杀", "色情")
        if any(term in text for term in blocked_terms):
            return {"status": "blocked", "reasonCode": "UNSAFE_CONTENT", "provider": "mock"}
        return {"status": "approved", "provider": "mock"}


class MockDynamicVisualProvider:
    def prepare_preview(self, shot: JsonObject, characters: list[JsonObject]) -> JsonObject:
        return {'model': 'mock-dynamic-v1（模拟）', 'adapter': 'mock',
                'parameters': {'duration': shot.get('durationSec')},
                'images': [], 'prompt': None, 'calls': {'text': 0, 'video': 0}}

    async def generate(self, shot: JsonObject, character_inputs: list[JsonObject]) -> JsonObject:
        version = uuid4().hex[:8]
        return {
            "id": f"visual-{shot['id']}-{version}",
            "shotId": shot["id"],
            "type": "dynamic-video",
            "mediaType": "video",
            "durationMs": int(float(shot["durationSec"]) * 1000),
            "width": 1080,
            "height": 1920,
            "fps": 30,
            "provider": "mock",
            "modelVersion": "mock-dynamic-v1",
            "objectKey": f"mock/{shot['id']}/{version}.mp4",
            "characterRefs": [item["id"] for item in character_inputs],
        }


class MockTtsProvider:
    async def generate(self, shot_id: str, speaker_id: str, text: str) -> JsonObject:
        duration_ms = max(1200, len(text.strip()) * 260)
        version = uuid4().hex[:8]
        return {
            "id": f"audio-{shot_id}-{version}",
            "shotId": shot_id,
            "speakerId": speaker_id,
            "text": text,
            "durationMs": duration_ms,
            "objectKey": f"mock/{shot_id}/{version}.wav",
        }


class MockLipSyncProvider:
    async def generate(
        self, shot_id: str, audio_asset: JsonObject, dialogue: JsonObject
    ) -> JsonObject:
        return {
            "id": f"lipsync-{shot_id}-{uuid4().hex[:8]}",
            "shotId": shot_id,
            "audioAssetId": audio_asset["id"],
            "startMs": dialogue["startMs"],
            "endMs": dialogue["endMs"],
            "objectKey": f"mock/{shot_id}/lipsync.json",
        }


class MockCompositionProvider:
    async def compose(self, project: JsonObject) -> JsonObject:
        return {
            "files": ["video.mp4", "cover.jpg", "subtitles.srt"],
            "format": "h264-aac-1080x1920-30fps",
            "projectId": project["id"],
            "artifacts": {
                "video.mp4": b"ComicFlow mock export: video.mp4\n",
                "cover.jpg": b"ComicFlow mock export: cover.jpg\n",
                "subtitles.srt": b"ComicFlow mock export: subtitles.srt\n",
            },
        }
