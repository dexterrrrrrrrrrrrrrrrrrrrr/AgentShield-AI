"""Mocked Colima/API regression tests; not real Mac isolation validation."""

import json

import pytest
from test_sandbox import fake_client

from app.sandbox.manager import DockerAdapter, Unavailable
from app.sandbox.readiness import daemon_observations, supports_v2_probe
from scripts.validate_sandbox import validate


def observed(**changes):
    return dict(
        uid=65534,
        memory="134217728",
        swap="0",
        pids="32",
        cpu="100000 100000",
        ro=True,
        workspace=True,
        network=True,
        nnp=True,
        caps=True,
        seccomp=True,
        cgroup_path="/",
        **changes,
    )


def client_with(settings, values=None):
    client, created = fake_client(settings, json.dumps(values or observed()).encode())
    client.info.return_value = {
        "Architecture": "aarch64",
        "CgroupDriver": "cgroupfs",
        "CgroupVersion": "2",
        "MemoryLimit": True,
        "SwapLimit": True,
        "PidsLimit": True,
        "CpuCfsQuota": True,
    }
    return client, created


@pytest.mark.parametrize(
    "flags",
    [
        {},
        {
            "MemoryLimit": False,
            "SwapLimit": None,
            "PidsLimit": False,
            "CpuCfsQuota": None,
        },
    ],
)
def test_colima_arm64_missing_legacy_flags_requires_effective_probe(settings, flags):
    client, created = client_with(settings)
    client.info.return_value.update(flags)
    adapter = DockerAdapter(settings, lambda: client)
    assert adapter.readiness() == {"ready": True, "code": "READY"}
    assert len(created) == 1
    assert adapter.last_probe["memory"] == "134217728"
    assert supports_v2_probe(client.info.return_value)
    assert daemon_observations(client.info.return_value)["Architecture"] == "aarch64"


@pytest.mark.parametrize(
    "field,value",
    [
        ("memory", "max"),
        ("memory", "34359738368"),
        ("pids", "max"),
        ("pids", "64"),
        ("cpu", "max 100000"),
        ("cpu", "400000 100000"),
        ("cpu", "-1 100000"),
        ("cpu", "0 100000"),
        ("cpu", "100000 0"),
        ("cgroup_path", "/unexpected"),
        ("swap", "max"),
        ("swap", "1"),
        ("seccomp", False),
        ("workspace", False),
    ],
)
def test_actual_limit_mismatch_fails_even_with_positive_metadata(
    settings, field, value
):
    values = observed()
    values[field] = value
    client, _ = client_with(settings, values)
    adapter = DockerAdapter(settings, lambda: client)
    assert not adapter.readiness()["ready"]
    with pytest.raises(Unavailable):
        adapter.execute("print(1)")


def test_missing_effective_controller_files_and_runtime_failure(settings):
    client, _ = client_with(settings)
    adapter = DockerAdapter(settings, lambda: client)
    # Trusted probe fails before producing results when a cgroup file is absent.
    adapter._run = lambda *a, **kw: {"status": "failed", "stdout": ""}
    assert not adapter.readiness()["ready"]
    client.info.side_effect = RuntimeError("private daemon diagnostics")
    assert adapter.readiness() == {"ready": False, "code": "SANDBOX_UNAVAILABLE"}


@pytest.mark.parametrize(
    "info",
    [
        {},
        {"CgroupDriver": "none", "CgroupVersion": "2"},
        {"CgroupDriver": "cgroupfs", "CgroupVersion": "1"},
    ],
)
def test_unknown_or_incompatible_namespace_still_denied(info):
    assert not supports_v2_probe(info)


def test_validator_does_not_short_circuit_valid_colima_on_wrong_case_field(settings):
    client, _ = client_with(settings)
    client.containers.list.return_value = []
    adapter = DockerAdapter(settings, lambda: client)
    # Validate only preflight; no synthetic result may be reported as live PASS.
    adapter.readiness = lambda: {"ready": False, "code": "SANDBOX_UNAVAILABLE"}
    report = validate(settings, client, lambda s: adapter)
    assert report["status"] == "BLOCKED"
    assert "effective limits" in report["reason"]
    assert report["daemon"]["CpuCfsQuota"] is True
    assert "CPUCfsQuota" not in report["daemon"]
