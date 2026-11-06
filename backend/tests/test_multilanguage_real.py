"""Opt-in actual runtime smoke tests; never substitute a mocked adapter."""
import os

import pytest
from app.sandbox.manager import DockerAdapter
from scripts.validate_multilanguage import PROGRAMS

@pytest.mark.skipif(os.environ.get('RUN_SANDBOX_INTEGRATION') != '1', reason='Requires opt-in compatible real Docker and operator-provisioned images')
@pytest.mark.parametrize('language', PROGRAMS)
def test_real_registered_runtime(settings, language):
    settings.sandbox_enabled = True
    adapter = DockerAdapter(settings)
    assert adapter.readiness(language)['ready'], 'SANDBOX_UNAVAILABLE: real controls or image not verified'
    outcome = adapter.execute(PROGRAMS[language], language=language)
    assert outcome['status'] == 'completed'
    assert outcome['stdout'] == 'hello\n'
    client = adapter.factory()
    try:
        assert not client.containers.list(all=True, filters={'label':'agentshield.sandbox=true'})
    finally:
        client.close()
