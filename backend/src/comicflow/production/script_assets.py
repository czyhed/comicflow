"""Invalidate saved media when edited script inputs change; never delete files."""
from comicflow.domain.models import JsonObject


def _shot_inputs(script: JsonObject) -> dict[str, JsonObject]:
    scenes = script.get('scenes', [])
    result = {}
    for shot in script.get('shots', []):
        scene_id = shot.get('sceneId') or next(
            (s['id'] for s in scenes if shot['id'] in s.get('shotIds', [])), None)
        scene = next((s for s in scenes if s.get('id') == scene_id), None)
        result[shot['id']] = {'shot': shot, 'scene': scene}
    return result


def invalidate_edited_script_assets(project: JsonObject, previous: JsonObject) -> None:
    before = _shot_inputs(previous)
    after = _shot_inputs(project.get('script') or {})
    changed = {sid for sid in before.keys() | after.keys() if before.get(sid) != after.get(sid)}
    affected = set(changed)
    visuals = project.get('visualAssets', [])
    while True:
        dependents = {asset['shotId'] for asset in visuals if asset.get('valid')
                      and asset.get('cascadeFromShotId') in affected} - affected
        if not dependents:
            break
        affected.update(dependents)
    for group in ('visualAssets', 'audioAssets', 'lipSyncAssets'):
        for asset in project.get(group, []):
            if asset.get('valid') and asset.get('shotId') in affected:
                asset.update(valid=False, invalidatedReason=(
                    'input-changed' if asset['shotId'] in changed else 'dependency-changed'))
    for shot_id in affected:
        project.get('timelines', {}).pop(shot_id, None)
    project.update(exportManifest=None, downstreamInvalidated=True)
