"""Mocked Docker phase sequencing; no source runs on the host."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock
import base64
from docker.errors import APIError

import pytest
from app.sandbox import multilang
from app.sandbox.manager import Unavailable
from app.sandbox.registry import LANGUAGES


def result(status='completed', stdout='', exit_code=0):
    return dict(status=status, stdout=stdout, stderr='', exit_code=exit_code,
                duration=0.1, truncated=False, error_category=None)


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('failure', ['none', 'compile', 'guard', 'timeout', 'output', 'stage'])
def test_phase_boundaries(language, failure, monkeypatch):
    compiled = LANGUAGES[language].compilation_required
    adapter = MagicMock()
    adapter.s = SimpleNamespace(sandbox_code_bytes=32768, sandbox_memory_mb=128,
        sandbox_pids=32, sandbox_cpus=1, sandbox_timeout=10,
        sandbox_compile_timeout=10, sandbox_output_bytes=65536)
    adapter.options.return_value = {}
    adapter.valid_probe.return_value = failure != 'guard'
    client = MagicMock()
    container = client.containers.create.return_value
    container.attrs = {'State': {}}
    container.put_archive.side_effect = APIError('container rootfs is marked read-only')
    calls = []
    def phase(*args):
        calls.append(args)
        if len(calls) == 1: return result(stdout=json.dumps({}))
        if len(calls) == 2:
            command = args[3]
            assert command[4].endswith(multilang.STAGE)
            assert command[6] == LANGUAGES[language].filename
            assert base64.b64decode(json.loads(command[7])[0]) == b'test source'
            return result('failed', exit_code=125) if failure == 'stage' else result()
        if failure == 'compile' and compiled: return result('failed', exit_code=1)
        if failure in ('timeout', 'output'):
            return result('timed_out' if failure == 'timeout' else 'output_limit', exit_code=137)
        return result(stdout='ok\n')
    monkeypatch.setattr(multilang, 'execute_phase', phase)
    if failure in ('guard', 'stage'):
        with pytest.raises(Unavailable): multilang.run_job(adapter, client, language, 'test source', '')
        container.put_archive.assert_not_called()
    else:
        actual = multilang.run_job(adapter, client, language, 'test source', '')
        if compiled and failure != 'none':
            assert len(calls) == 3  # Probe, stage, failed compile; no program.
            assert actual['stdout'] == ''
        elif failure == 'none':
            assert actual['stdout'] == 'ok\n'
            assert len(calls) == (4 if compiled else 3)
    container.put_archive.assert_not_called()
    container.remove.assert_called_once_with(force=True, v=True)


def test_payload_is_data_only_and_preserves_utf8():
    code = "print('λ'); # \"quoted\"\n"
    stdin = "héllo\n"
    payload = multilang.source_payload(code, stdin)
    assert [base64.b64decode(v).decode() for v in json.loads(payload)] == [code, stdin]
    assert len(multilang.source_payload("a" * 32768, "b" * 8192)) < 56000
    assert code not in payload
