"""Small read-only grouping of retained project data; never a deletion recommendation."""
from collections import Counter, defaultdict

from .inventory import TERMINAL, media_references


def character_ids(value):
    found = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key == 'characterIds' and isinstance(item, list):
                found.update(x for x in item if isinstance(x, str))
            else:
                found.update(character_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.update(character_ids(item))
    return found


def media_groups(value, category='current'):
    groups = defaultdict(set)
    if isinstance(value, dict):
        if value.get('valid') is False:
            category = 'history'
        for key, item in value.items():
            group = category
            if 'candidate' in key.lower():
                group = 'candidate'
            elif key in {'scriptVersions', 'history'}:
                group = 'history'
            elif key == 'exportManifest':
                group = 'export'
            if key.lower().endswith('objectkey') and isinstance(item, str) and item:
                groups[group].add(item)
            elif key == 'objectKeys' and isinstance(item, dict):
                groups[group].update(x for x in item.values() if isinstance(x, str) and x)
            else:
                for name, keys in media_groups(item, group).items():
                    groups[name].update(keys)
    elif isinstance(value, list):
        for item in value:
            for name, keys in media_groups(item, category).items():
                groups[name].update(keys)
    return groups


def project_report(projects, characters, jobs, object_keys):
    cards = {r['id']: r['payload'] for r in characters}
    pids = {r['id'] for r in projects}
    titles, object_users, card_users = defaultdict(list), defaultdict(set), defaultdict(set)
    items = []
    for row in projects:
        pid, payload = row['id'], row['payload']
        project = payload['project']
        script = project.get('script') or {}
        title = script.get('title') or project.get('title') or ''
        if title:
            titles[title].append(pid)
        linked = [job for job in jobs if job['project_id'] == pid]
        refs = character_ids(project)
        for job in linked:
            refs.update(character_ids(job['payload']))
            if job['payload'].get('characterId'):
                refs.add(job['payload']['characterId'])
        owned = {cid for cid, card in cards.items() if card.get('projectId') == pid}
        all_cards = refs | owned
        sources = [(payload, 'current', 'project')]
        sources += [(cards[cid], 'current', f'character:{cid}')
                    for cid in sorted(all_cards) if cid in cards]
        sources += [(job['payload'], 'job-retained', f"job:{job['id']}") for job in linked]
        groups, unresolved = defaultdict(set), []
        for value, category, path in sources:
            for name, keys in media_groups(value, category).items():
                groups[name].update(keys)
            unresolved.extend(media_references(value, path)[1])
        keys = set().union(*groups.values()) if groups else set()
        for key in keys:
            object_users[key].add(pid)
        for cid in all_cards:
            card_users[cid].add(pid)
        unfinished = [job['id'] for job in linked
                      if job['payload'].get('status') not in TERMINAL or job.get('active_slot')]
        legacy = payload.get('jobs') or []
        unfinished += [job.get('id', 'legacy-without-id') for job in legacy
                       if job.get('status') not in TERMINAL]
        session = project.get('generationSession') or {}
        items.append({
            'id': pid, 'title': title or '未保存标题',
            'createdAt': project.get('createdAt'), 'updatedAt': str(row['updated_at']),
            'stage': project.get('stage'), 'version': project.get('version'),
            'hasStory': bool((project.get('input') or {}).get('story')
                             or project.get('generatedStoryText')
                             or project.get('generationPartialText')),
            'hasScript': bool(script), 'scriptVersions': len(project.get('scriptVersions') or []),
            'scenes': len(script.get('scenes') or []), 'shots': len(script.get('shots') or []),
            'characterIds': sorted(refs), 'ownedCharacterIds': sorted(owned),
            'missingCharacterIds': sorted(refs - cards.keys()),
            'media': {name: sorted(value) for name, value in sorted(groups.items())},
            'objectKeys': sorted(keys), 'missingObjectKeys': sorted(keys - object_keys),
            'unresolvedMedia': sorted(set(unresolved)),
            'jobs': dict(Counter(f"{job['kind']}:{job['payload'].get('status', 'unknown')}"
                                 for job in linked)),
            'legacyJobs': dict(Counter(job.get('status', 'unknown') for job in legacy)),
            'unfinishedJobIds': unfinished, 'generationSessionStatus': session.get('status'),
            'hasExport': bool(project.get('exportManifest')),
        })
    duplicates = {title: ids for title, ids in titles.items() if len(ids) > 1}
    for item in items:
        item['sharedObjectKeys'] = [key for key in item['objectKeys'] if len(object_users[key]) > 1]
        item['sharedCharacterIds'] = [
            cid for cid in item['characterIds'] + item['ownedCharacterIds']
            if len(card_users[cid]) > 1]
        item['sharedCharacterIds'] = sorted(set(item['sharedCharacterIds']))
        if item['missingObjectKeys'] or item['missingCharacterIds'] or item['unresolvedMedia']:
            item['category'] = '引用异常待修复'
        elif item['objectKeys'] or item['hasExport'] or item['unfinishedJobIds']:
            item['category'] = '有资产保留'
        elif item['title'] in duplicates:
            item['category'] = '疑似测试/重复待判断'
        else:
            item['category'] = '只有文本待用户判断'
    return {
        'items': items, 'categories': dict(Counter(item['category'] for item in items)),
        'duplicateTitles': duplicates,
        'sharedObjectReferences': {key: sorted(ids) for key, ids in object_users.items()
                                   if len(ids) > 1},
        'unassignedCharacterIds': sorted(set(cards) - card_users.keys()),
        'unassignedJobIds': [job['id'] for job in jobs if job['project_id'] not in pids],
        'classificationOnly': True,
    }


async def read_project_rows(conn):
    projects = [dict(row) for row in await conn.fetch(
        'SELECT id, payload, updated_at FROM project_states ORDER BY id')]
    characters = [dict(row) for row in await conn.fetch('SELECT id, payload FROM characters')]
    jobs = []
    for kind in ('image', 'video'):
        jobs += [dict(row, kind=kind) for row in await conn.fetch(
            f'SELECT id, project_id, active_slot, payload FROM {kind}_generation_jobs')]
    return projects, characters, jobs
