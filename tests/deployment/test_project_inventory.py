"""Read-only classification must never recommend disposal from weak signals."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from migration_tools.projects import project_report


def row(pid, **project):
    return {'id': pid, 'updated_at': '2026-09-22', 'payload': {
        'project': {'id': pid, 'input': {'story': '已写故事'}, **project}, 'jobs': []}}


def test_zero_shots_and_duplicate_title_keep_text_and_shared_assets():
    projects = [row('p1', script={'title': '同名', 'shots': []}),
                row('p2', script={'title': '同名', 'shots': [{'characterIds': ['c']} ]})]
    cards = [{'id': 'c', 'payload': {'projectId': 'p1', 'referenceBoardCandidate': {
        'objectKey': 'board.png'}}}]
    report = project_report(projects, cards, [], {'board.png'})
    assert report['duplicateTitles'] == {'同名': ['p1', 'p2']}
    assert all(p['category'] == '有资产保留' for p in report['items'])
    assert report['items'][0]['hasStory'] is True
    assert all(p['sharedObjectKeys'] == ['board.png'] for p in report['items'])
    assert all(p['media']['candidate'] == ['board.png'] for p in report['items'])


def test_missing_history_and_unknown_job_survive_classification_without_private_urls():
    projects = [row('p', visualAssets=[{'valid': False, 'objectKey': 'old.mp4'}])]
    jobs = [{'id': 'j', 'project_id': 'p', 'active_slot': None,
             'kind': 'video', 'payload': {'status': 'unknown',
                 'result': {'videoUrl': 'https://private.invalid/?secret=value'}}}]
    report = project_report(projects, [], jobs, set())
    item = report['items'][0]
    assert item['category'] == '引用异常待修复'
    assert item['missingObjectKeys'] == ['old.mp4']
    assert item['media']['history'] == ['old.mp4']
    assert item['unfinishedJobIds'] == ['j']
    assert 'private.invalid' not in str(report) and 'secret=value' not in str(report)


def test_text_only_duplicate_and_unowned_rows_are_reported_not_deleted():
    projects = [row('p1', script={'title': '重复'}), row('p2', script={'title': '重复'}),
                row('p3')]
    cards = [{'id': 'orphan', 'payload': {'projectId': 'missing'}}]
    report = project_report(projects, cards, [], set())
    assert len(report['items']) == 3
    assert report['items'][0]['category'] == '疑似测试/重复待判断'
    assert report['items'][2]['category'] == '只有文本待用户判断'
    assert report['unassignedCharacterIds'] == ['orphan']
