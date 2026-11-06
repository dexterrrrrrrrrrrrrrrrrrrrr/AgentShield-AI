"""Mocked Docker phase sequencing; no source runs on the host."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from app.sandbox import multilang
from app.sandbox.manager import Unavailable
from app.sandbox.registry import LANGUAGES


def result(status='completed', stdout='', exit_code=0):
    return dict(status=status, stdout=stdout, stderr='', exit_code=exit_code,
                duration=0.1, truncated=False, error_category=None)


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('failure', ['none', 'compile', 'guard', 'timeout', 'output'])
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
    calls = []
    def phase(*args):
        calls.append(args)
        if len(calls) == 1: return result(stdout=json.dumps({}))
        if failure == 'compile' and compiled: return result('failed', exit_code=1)
        if failure in ('timeout', 'output'):
            return result('timed_out' if failure == 'timeout' else 'output_limit', exit_code=137)
        return result(stdout='ok\n')
    monkeypatch.setattr(multilang, 'execute_phase', phase)
    if failure == 'guard':
        with pytest.raises(Unavailable): multilang.run_job(adapter, client, language, 'test source', '')
        container.put_archive.assert_not_called()
    else:
        actual = multilang.run_job(adapter, client, language, 'test source', '')
        if compiled and failure != 'none':
            assert len(calls) == 2  # Compilation failure never starts program.
            assert actual['stdout'] == ''
        elif failure == 'none':
            assert actual['stdout'] == 'ok\n'
            assert len(calls) == (3 if compiled else 2)
    container.remove.assert_called_once_with(force=True, v=True)
