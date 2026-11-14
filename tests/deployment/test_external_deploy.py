"""Exercise release ordering without a Docker daemon or real credentials."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('workers', [False, True])
@pytest.mark.parametrize('failure', ['', 'build', 'schema', 'secret', 'worker-delayed', 'worker-unavailable'])
def test_external_release_is_explicit_and_fail_closed(tmp_path, failure, workers):
    bash = shutil.which('bash')
    if os.name == 'nt':
        bash = 'D:/a/git/Git/bin/bash.exe'
    assert bash and Path(bash).exists()
    (tmp_path / 'deploy').mkdir()
    (tmp_path / 'bin').mkdir()
    shutil.copyfile(ROOT / 'deploy/backend-external.sh', tmp_path / 'deploy/backend-external.sh')
    (tmp_path / 'bin/docker').write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" >> "$CHECK_LOG"\n'
        'case " $* " in\n'
        '*" build api "*) [ "$FAIL_STEP" = build ] && exit 17 ;;\n'
        '*" current --check-heads "*) [ "$FAIL_STEP" = schema ] && exit 18 ;;\n'
        '*" inspect ping "*)\n'
        '  if [ "$FAIL_STEP" = worker-unavailable ]; then exit 19; fi\n'
        '  if [ "$FAIL_STEP" = worker-delayed ] && [ ! -e "$CHECK_LOG.ready" ]; then\n'
        '    touch "$CHECK_LOG.ready"; exit 19\n'
        '  fi ;;\n'
        'esac\nexit 0\n', newline='\n',
    )
    (tmp_path / 'bin/sleep').write_text('#!/bin/sh\nexit 0\n', newline='\n')
    log = tmp_path / 'calls.txt'
    env = dict(os.environ, APP_VERSION='fixture', BACKEND_EXTERNAL_ENV='',
               CHECK_LOG=log.as_posix(), FAIL_STEP=failure,
               DEPLOY_WORKERS='true' if workers else 'false')
    if failure != 'secret':
        env['BACKEND_EXTERNAL_ENV'] = 'TEST_ONLY=fixture'
    result = subprocess.run(
        [bash, '-c', 'export PATH="$PWD/bin:$PATH"; sh deploy/backend-external.sh'],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=15,
    )
    calls = log.read_text().splitlines() if log.exists() else []
    assert not (tmp_path / '.env.server').exists()
    assert all('upgrade' not in call and '--pull' not in call
               and 'compose.backend.yml' not in call for call in calls)
    if not workers:
        assert all('worker' not in call and 'beat' not in call for call in calls)
    if failure in {'build', 'schema', 'secret'}:
        assert result.returncode != 0
        assert not any('up -d' in call for call in calls)
    elif workers and failure == 'worker-unavailable':
        assert result.returncode != 0
        pings = [call for call in calls if 'inspect ping' in call]
        assert 1 < len(pings) <= 12
        assert not any('/api/projects' in call for call in calls)
    else:
        assert result.returncode == 0, result.stderr
        schema = next(i for i, call in enumerate(calls) if 'current --check-heads' in call)
        start = next(i for i, call in enumerate(calls) if 'up -d' in call)
        assert schema < start
        assert calls[start].endswith('api worker beat' if workers else 'api')
        if workers:
            assert any('inspect ping' in call for call in calls)
            if failure == 'worker-delayed':
                assert len([call for call in calls if 'inspect ping' in call]) == 2


def test_production_overlay_preserves_external_targets(tmp_path):
    from test_data_connections import VALUES, external_fixture

    external_fixture(tmp_path, VALUES)
    shutil.copyfile(ROOT / 'deploy/compose.external-production.yml',
                    tmp_path / 'deploy/compose.external-production.yml')
    env = {key: value for key, value in os.environ.items()
           if key.upper() in {
               'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'USERPROFILE', 'HOME',
               'PROGRAMFILES', 'PROGRAMFILES(X86)', 'PROGRAMDATA', 'APPDATA', 'LOCALAPPDATA',
           }}
    result = subprocess.run([
        'docker', 'compose', '--env-file', '.env.server', '-p', 'comicflow-deploy-test',
        '-f', 'deploy/compose.external-data.yml', '-f', 'deploy/compose.external-production.yml',
        'config', '--format', 'json'], cwd=tmp_path, env=env,
        capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)['services']
    assert set(services) == {'api'}
    assert not services['api'].get('ports')
    assert services['api']['networks']['edge']['aliases'] == ['comicflow-api']
    assert services['api']['environment']['DATABASE_URL'] == VALUES['DATABASE_URL']
