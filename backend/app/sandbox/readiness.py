"""Metadata selects the trusted probe; only effective kernel controls authorize code."""


def supports_v2_probe(info):
    # Legacy /info resource booleans can be missing/inconsistent under cgroup v2.
    # They must neither authorize user code nor veto a kernel-verified runtime.
    return str(info.get("CgroupVersion")) == "2" and info.get("CgroupDriver") in (
        "cgroupfs",
        "systemd",
    )


def daemon_observations(info):
    fields = (
        "Architecture",
        "CgroupDriver",
        "CgroupVersion",
        "MemoryLimit",
        "SwapLimit",
        "PidsLimit",
        "CpuCfsQuota",
    )
    return {key: info.get(key) for key in fields}
