"""Fixed commands executed ONLY by the Docker daemon inside a verified job container.

The backend never runs a compiler/program or shell. Docker exec exit codes, not
program-supplied JSON, determine phase status. /tmp remains a noexec mount; the
trusted native launcher deliberately executes the compiled ELF using a sealed
anonymous memfd. This grants native execution within the same container boundary.
"""
import io
import json
import tarfile
import time

from .registry import get_language

# This trusted launcher is a container command string, never evaluated on host.
GUARD = '''
e=json.loads(sys.argv[1]); q,period=map(int,v['cpu'].split())
if not (v['cgroup_path']=='/' and v['uid']==65534 and int(v['memory'])==e['memory'] and int(v['swap'])==0 and int(v['pids'])==e['pids'] and q>0 and period>0 and q/period<=e['cpus']+0.001 and all(v[k] for k in ('ro','workspace','network','nnp','caps','seccomp'))):
    raise SystemExit(125)
import resource
resource.setrlimit(resource.RLIMIT_CPU,(e['timeout']+1,e['timeout']+1))
resource.setrlimit(resource.RLIMIT_FSIZE,(16777216,16777216))
'''
LAUNCH = '''
args=json.loads(sys.argv[2])
f=os.open('/tmp/input.txt',os.O_RDONLY); os.dup2(f,0); os.close(f)
os.environ.clear(); os.environ.update(PATH='/usr/local/bin:/usr/bin:/bin',LANG='C.UTF-8',HOME='/tmp',TMPDIR='/tmp')
os.execv(args[0],args)
'''
NATIVE_LAUNCH = '''
import fcntl
f=os.open('/tmp/input.txt',os.O_RDONLY); os.dup2(f,0); os.close(f)
fd=os.memfd_create('program',os.MFD_CLOEXEC|os.MFD_ALLOW_SEALING)
with open('/tmp/program','rb') as source:
    while chunk:=source.read(65536): os.write(fd,chunk)
fcntl.fcntl(fd,fcntl.F_ADD_SEALS,fcntl.F_SEAL_WRITE|fcntl.F_SEAL_GROW|fcntl.F_SEAL_SHRINK|fcntl.F_SEAL_SEAL)
os.environ.clear()
os.execve(fd,['program'],{'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','HOME':'/tmp','TMPDIR':'/tmp'})
'''


def source_archive(language, code, stdin):
    """An in-memory tar of two fixed-name files; no host file access."""
    entry = get_language(language)
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        for name, content in ((entry.filename, code), ("input.txt", stdin)):
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size, info.uid, info.gid, info.mode = len(data), 65534, 65534, 0o600
            archive.addfile(info, io.BytesIO(data))
    return output.getvalue()


def execute_phase(adapter, client, container, command, timeout, cap):
    """Docker exec runs fixed trusted command vectors; never invoke a host process."""
    from .manager import Unavailable
    started = time.monotonic()
    execution = client.api.exec_create(container.id, command, stdout=True, stderr=True,
                                       stdin=False, tty=False, privileged=False, user="65534:65534",
                                       workdir="/tmp")
    sock = None
    try:
        sock = client.api.exec_start(execution["Id"], socket=True, tty=False)
        output, truncated, timed_out = adapter._frames(sock, cap, started + timeout, container)
        if truncated or timed_out:
            container.kill()
            container.wait(timeout=2)
        state = client.api.exec_inspect(execution["Id"])
        if state.get("Running") or state.get("ExitCode") is None:
            raise Unavailable("Runtime phase status unavailable")
        return {
            "status": "timed_out" if timed_out else "output_limit" if truncated else "completed" if state["ExitCode"] == 0 else "failed",
            "stdout": bytes(output[0]).decode(errors="ignore"),
            "stderr": bytes(output[1]).decode(errors="ignore"),
            "exit_code": state["ExitCode"],
            "duration": round(time.monotonic() - started, 3),
            "truncated": truncated,
            "output_bytes": sum(len(chunk) for chunk in output),
            "error_category": "TIMEOUT" if timed_out else "OUTPUT_LIMIT" if truncated else "PROGRAM_ERROR" if state["ExitCode"] else None,
        }
    finally:
        if sock is not None:
            sock.close()


def run_job(adapter, client, language, code, stdin):
    from .manager import CHECK, PROBE, Unavailable
    entry = get_language(language)
    if not code.strip() or "\0" in code or len(code.encode()) > adapter.s.sandbox_code_bytes or len(stdin.encode()) > 8192 or "\0" in stdin:
        raise Unavailable("Invalid runtime request")
    container = None
    started = time.monotonic()
    compile_result = None
    run_result = None
    try:
        # The holder cannot process submitted code. It only keeps the job alive.
        container = client.containers.create(command=["python", "-I", "-u", "-c", "import signal; signal.pause()"], use_config_proxy=False, **adapter.options(language))
        adapter.verify_container(container)
        container.start()
        # Inspect effective kernel settings in THIS container before even uploading source.
        probe = execute_phase(adapter, client, container, ["python", "-I", "-u", "-c", PROBE], 3, 4096)
        values = json.loads(probe["stdout"])
        if probe["status"] != "completed" or not adapter.valid_probe(values):
            raise Unavailable("Effective isolation limits do not match")
        if not container.put_archive("/tmp", source_archive(language, code, stdin)):
            raise Unavailable("Unable to stage source")
        def command(args, timeout, native=False):
            expected = json.dumps({"memory": adapter.s.sandbox_memory_mb * 1048576, "pids": adapter.s.sandbox_pids, "cpus": adapter.s.sandbox_cpus, "timeout": timeout})
            return ["python", "-I", "-u", "-c", CHECK + GUARD + (NATIVE_LAUNCH if native else LAUNCH), expected, json.dumps(args)]
        remaining = adapter.s.sandbox_output_bytes
        if entry.compilation_required:
            compile_timeout = getattr(adapter.s, "sandbox_compile_timeout", 10)
            compile_result = execute_phase(adapter, client, container, command(entry.compile_command, compile_timeout), compile_timeout, remaining)
            remaining -= compile_result.get("output_bytes", len(compile_result["stdout"].encode()) + len(compile_result["stderr"].encode()))
            if compile_result["exit_code"] == 125:
                raise Unavailable("Inner container guard refused compilation")
        if compile_result is None or compile_result["status"] == "completed":
            run_result = execute_phase(adapter, client, container, command(entry.run_command, adapter.s.sandbox_timeout, entry.family == "native"), adapter.s.sandbox_timeout, max(0, remaining))
            if run_result["exit_code"] == 125:
                raise Unavailable("Inner container guard refused execution")
        result = run_result or compile_result
        container.reload()
        result = dict(result)
        result.update(language=language, compile_status=compile_result["status"] if compile_result else "not_required",
                      compile_stdout=compile_result["stdout"] if compile_result else "", compile_stderr=compile_result["stderr"] if compile_result else "",
                      stdout=run_result["stdout"] if run_result else "", stderr=run_result["stderr"] if run_result else "",
                      compile_duration_ms=round(compile_result["duration"] * 1000) if compile_result else 0,
                      execution_duration_ms=round(run_result["duration"] * 1000) if run_result else 0,
                      duration=round(time.monotonic()-started,3),
                      oom_killed=bool(container.attrs["State"].get("OOMKilled",False)))
        if compile_result and compile_result["status"] != "completed":
            result["error_category"] = "COMPILE_" + (compile_result["error_category"] or "ERROR")
        return result
    finally:
        if container is not None:
            container.remove(force=True,v=True)
