"""Synchronous Docker adapter runs in a shielded worker; never executes code on host.

No implicit image pulls, Docker contexts, client proxy injection, or environment
forwarding. A future microVM adapter can implement readiness()/execute().
"""

import asyncio
import json
import struct
import time
import uuid

import docker
from docker.types import LogConfig, Ulimit

from .policy import IMAGE
from .readiness import supports_v2_probe

# Fixed trusted probe only, not model/user-controlled. Namespaced cgroup-v2
# files must reflect the requested limits, rather than the host's limits.
CHECK = """import os,json,pathlib,sys
membership=pathlib.Path('/proc/self/cgroup').read_text().splitlines()
cgroup_path=next(line.split(':',2)[2] for line in membership if line.startswith('0::'))
if cgroup_path!='/': raise RuntimeError('Expected private cgroup namespace root')
p=pathlib.Path('/sys/fs/cgroup')
status=pathlib.Path('/proc/self/status').read_text()
tmp=os.statvfs('/tmp')
workspace=all(tmp.f_flag & flag for flag in (os.ST_NOEXEC,os.ST_NOSUID,os.ST_NODEV)) and tmp.f_blocks*tmp.f_frsize<=16777216
v=dict(cgroup_path=cgroup_path,workspace=workspace,uid=os.getuid(),memory=(p/'memory.max').read_text().strip(),swap=(p/'memory.swap.max').read_text().strip(),pids=(p/'pids.max').read_text().strip(),cpu=(p/'cpu.max').read_text().strip(),ro=bool(os.statvfs('/').f_flag & os.ST_RDONLY),network=set(x.name for x in pathlib.Path('/sys/class/net').iterdir()) <= {'lo'},nnp='NoNewPrivs:\\t1' in status,caps='CapEff:\\t0000000000000000' in status,seccomp='Seccomp:\\t2' in status)
"""
PROBE = CHECK + "\nprint(json.dumps(v))"
# This string is evaluated ONLY by Python inside the isolated container.
# User code is an argv data value, never evaluated by the backend process.
RUNNER = (
    CHECK
    + """
e=json.loads(sys.argv[2]); q,period=map(int,v['cpu'].split())
if not (v['uid']==65534 and int(v['memory'])==e['memory'] and int(v['swap'])==0 and int(v['pids'])==e['pids'] and q>0 and period>0 and q/period<=e['cpus']+0.001 and all(v[k] for k in ('ro','workspace','network','nnp','caps','seccomp'))):
    raise SystemExit(125)
import resource
resource.setrlimit(resource.RLIMIT_CPU,(e['timeout']+1,e['timeout']+1))
exec(compile(sys.argv[1],'<sandbox>','exec'),{'__name__':'__main__'})
"""
)


class Unavailable(Exception):
    pass


class DockerAdapter:
    def __init__(self, settings, factory=None):
        self.s = settings
        self.last_probe = None
        self.factory = factory or (
            lambda: docker.DockerClient(base_url=settings.sandbox_docker_url, timeout=2)
        )

    def options(self):
        s = self.s
        return dict(
            image=IMAGE,
            user="65534:65534",
            working_dir="/tmp",
            privileged=False,
            network_mode="none",
            network_disabled=True,
            read_only=True,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            mem_limit=s.sandbox_memory_mb * 1048576,
            memswap_limit=s.sandbox_memory_mb * 1048576,
            nano_cpus=int(s.sandbox_cpus * 1e9),
            pids_limit=s.sandbox_pids,
            ipc_mode="private",
            cgroupns="private",
            tmpfs={"/tmp": "rw,nosuid,nodev,noexec,size=16777216,mode=1777"},
            environment={},
            volumes={},
            mounts=[],
            stdin_open=False,
            tty=False,
            ulimits=[
                Ulimit(name="nofile", soft=64, hard=64),
                Ulimit(name="core", soft=0, hard=0),
            ],
            log_config=LogConfig(type="none"),
            labels={"agentshield.sandbox": "true"},
            name="agentshield-sandbox-" + uuid.uuid4().hex,
        )

    @staticmethod
    def _frames(sock, cap, deadline, container):
        output = [bytearray(), bytearray()]
        buffer = bytearray()
        truncated = False
        sock._sock.settimeout(0.2)
        while True:
            if time.monotonic() > deadline:
                return output, truncated, True
            try:
                data = sock._sock.recv(4096)
            except (TimeoutError, OSError):
                container.reload()
                if not container.attrs["State"]["Running"]:
                    break
                continue
            if not data:
                break
            buffer.extend(data)
            while len(buffer) >= 8:
                size = struct.unpack(">I", buffer[4:8])[0]
                if size > 1048576:
                    raise Unavailable("Invalid Docker stream framing")
                if len(buffer) < 8 + size:
                    break
                stream = 0 if buffer[0] == 1 else 1
                chunk = buffer[8 : 8 + size]
                del buffer[: 8 + size]
                remaining = cap - sum(len(x) for x in output)
                output[stream].extend(chunk[: max(0, remaining)])
                if len(chunk) > remaining:
                    truncated = True
                    return output, truncated, False
        return output, truncated, False

    def _run(self, client, code, probe=False):
        container = None
        sock = None
        started = time.monotonic()
        try:
            opts = self.options()
            command = (
                ["python", "-I", "-u", "-c", PROBE]
                if probe
                else [
                    "python",
                    "-I",
                    "-u",
                    "-c",
                    RUNNER,
                    code,
                    json.dumps(
                        {
                            "memory": self.s.sandbox_memory_mb * 1048576,
                            "pids": self.s.sandbox_pids,
                            "cpus": self.s.sandbox_cpus,
                            "timeout": self.s.sandbox_timeout,
                        }
                    ),
                ]
            )
            container = client.containers.create(
                command=command,
                use_config_proxy=False,
                **opts,
            )
            # Inspect before starting: no host mounts/namespaces or unexpected env.
            container.reload()
            cfg = container.attrs
            host = cfg["HostConfig"]
            if (
                cfg["Config"]["User"] != "65534:65534"
                or not host["ReadonlyRootfs"]
                or host["Privileged"]
                or host["NetworkMode"] != "none"
                or host.get("PidMode")
                or host.get("CgroupnsMode") != "private"
                or host.get("CapAdd")
                or host.get("MemorySwap") != self.s.sandbox_memory_mb * 1048576
                or host.get("IpcMode") != "private"
                or host.get("Binds")
                or any(
                    m.get("Type") != "tmpfs" or m.get("Destination") != "/tmp"
                    for m in cfg.get("Mounts", [])
                )
                or "ALL" not in host["CapDrop"]
                or host["Memory"] != self.s.sandbox_memory_mb * 1048576
                or host["PidsLimit"] != self.s.sandbox_pids
                or host["NanoCpus"] != int(self.s.sandbox_cpus * 1e9)
                or not any(
                    x in ("no-new-privileges", "no-new-privileges:true")
                    for x in host["SecurityOpt"]
                )
                or any(
                    "=" in e
                    and e.split("=", 1)[0]
                    not in {
                        "PATH",
                        "LANG",
                        "PYTHON_VERSION",
                        "PYTHON_SHA256",
                        "GPG_KEY",
                    }
                    for e in cfg["Config"].get("Env", [])
                )
            ):
                raise Unavailable("Container restrictions could not be verified")
            sock = container.attach_socket(
                params={"stdout": True, "stderr": True, "stream": True}
            )
            execution_deadline = time.monotonic() + self.s.sandbox_timeout
            container.start()
            output, truncated, timed_out = self._frames(
                sock,
                4096 if probe else self.s.sandbox_output_bytes,
                execution_deadline,
                container,
            )
            if truncated or timed_out:
                try:
                    container.kill()
                except docker.errors.APIError as exc:
                    if exc.status_code != 409:
                        raise
            result = container.wait(timeout=2)
            container.reload()
            return dict(
                status="timed_out"
                if timed_out
                else "output_limit"
                if truncated
                else "completed"
                if result["StatusCode"] == 0
                else "failed",
                stdout=bytes(output[0]).decode(errors="ignore"),
                stderr=bytes(output[1]).decode(errors="ignore"),
                exit_code=result["StatusCode"],
                duration=round(time.monotonic() - started, 3),
                truncated=truncated,
                oom_killed=bool(container.attrs["State"].get("OOMKilled", False)),
                error_category="TIMEOUT"
                if timed_out
                else "OUTPUT_LIMIT"
                if truncated
                else "PROGRAM_ERROR"
                if result["StatusCode"]
                else None,
            )
        finally:
            try:
                if sock is not None:
                    sock.close()
            finally:
                if container is not None:
                    container.remove(force=True, v=True)

    def readiness(self):
        self.last_probe = None
        client = None
        try:
            client = self.factory()
            info = client.info()
            if not supports_v2_probe(info):
                raise Unavailable("A supported cgroup-v2 namespace is required")
            if client.containers.list(
                all=True, filters={"label": "agentshield.sandbox=true"}
            ):
                raise Unavailable(
                    "Existing sandbox containers require operator recovery"
                )
            client.images.get(IMAGE)  # No auto-pull and no user-selected image.
            result = self._run(client, PROBE, probe=True)
            v = json.loads(result["stdout"])
            self.last_probe = v
            quota, period = map(int, v["cpu"].split())
            if (
                result["status"] != "completed"
                or v["cgroup_path"] != "/"
                or v["uid"] != 65534
                or int(v["memory"]) != self.s.sandbox_memory_mb * 1048576
                or int(v["swap"]) != 0
                or int(v["pids"]) != self.s.sandbox_pids
                or quota <= 0
                or period <= 0
                or quota / period > self.s.sandbox_cpus + 0.001
                or not all(
                    v[k]
                    for k in ("ro", "workspace", "network", "nnp", "caps", "seccomp")
                )
            ):
                raise Unavailable("Effective isolation limits do not match")
            return {"ready": True, "code": "READY"}
        except Exception:
            return {"ready": False, "code": "SANDBOX_UNAVAILABLE"}
        finally:
            if client is not None:
                client.close()

    def execute(self, code):
        # Revalidate immediately before each execution. Never cache readiness.
        if not self.readiness()["ready"]:
            raise Unavailable("SANDBOX_UNAVAILABLE")
        client = self.factory()
        try:
            result = self._run(client, code)
            if result["exit_code"] == 125:
                raise Unavailable("SANDBOX_UNAVAILABLE")
            return result
        finally:
            client.close()


class SandboxManager:
    def __init__(self, settings, adapter=None):
        self.s = settings
        self.adapter = adapter or DockerAdapter(settings)
        self.lock = asyncio.Lock()
        self.failed = False

    async def _drain(self, task):
        # Repeated cancellation must never release capacity before the lifecycle
        # thread confirms cleanup. Cancellation remains observable to the caller.
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                self.failed = True
                break
        try:
            task.result()
        except BaseException:
            self.failed = True

    async def readiness(self):
        if not self.s.sandbox_enabled or self.failed:
            return {"ready": False, "code": "SANDBOX_UNAVAILABLE"}
        if self.lock.locked():
            return {"ready": False, "code": "SANDBOX_UNAVAILABLE"}
        async with self.lock:
            task = asyncio.create_task(asyncio.to_thread(self.adapter.readiness))
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                await self._drain(task)
                raise

    async def execute(self, code):
        if not self.s.sandbox_enabled or self.failed:
            raise Unavailable("SANDBOX_UNAVAILABLE")
        if self.lock.locked():
            raise Unavailable("SANDBOX_BUSY")
        async with self.lock:
            task = asyncio.create_task(asyncio.to_thread(self.adapter.execute, code))
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                # The worker owns cleanup. Keep capacity locked until it ends.
                await self._drain(task)
                raise
            except Exception:
                self.failed = True
                raise Unavailable("SANDBOX_UNAVAILABLE") from None
