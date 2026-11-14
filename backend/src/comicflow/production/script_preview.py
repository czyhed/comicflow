from comicflow.domain.models import JsonObject
from comicflow.providers.message_contract import normalize_script_message


def normalize_preview(script: JsonObject, *, target_duration_sec: int) -> JsonObject:
    result = normalize_script_message(
        {'kind': 'script', 'version': 1, 'content': script},
        target_duration_sec=target_duration_sec,
    )
    scene_ids: set[str] = set()
    for scene in result['scenes']:
        # Scene context fields (time, location, narrativeGoal, conflict, turningPoint)
        # are optional metadata for the screenwriter. The downstream pipeline does not
        # use them. Only validate type if present; empty or missing is acceptable.
        if scene['id'] in scene_ids:
            raise RuntimeError('PROVIDER_INVALID_RESPONSE')
        for field in ('time', 'location', 'narrativeGoal', 'conflict', 'turningPoint'):
            value = scene.get(field)
            if value is not None and not isinstance(value, str):
                raise RuntimeError('PROVIDER_INVALID_RESPONSE')
        scene_ids.add(scene['id'])
    for shot in result['shots']:
        # The shared contract accepts explicit silence and rejects unspecified
        # speech. Fill the unused key only after validating that distinction.
        lines = {field: shot.get(field, '') for field in ('dialogue', 'narration')}
        if any(not isinstance(value, str) for value in lines.values()):
            raise RuntimeError('PROVIDER_INVALID_RESPONSE')
        for field, value in lines.items():
            shot[field] = value
    return result
