"""Trusted, immutable language recipes. Request data cannot select commands/images."""
from dataclasses import asdict, dataclass
from types import MappingProxyType
import re

PYTHON_IMAGE = "python@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30"
RUNTIME_REVISION = "1"


@dataclass(frozen=True)
class Language:
    id: str
    display_name: str
    extension: str
    version: str
    family: str
    filename: str
    compile_command: tuple[str, ...] = ()
    run_command: tuple[str, ...] = ()
    version_command: tuple[str, ...] = ()
    version_prefix: str = ""

    @property
    def compilation_required(self):
        return bool(self.compile_command)


JVM = ("-Xms8m", "-Xmx48m", "-Xss256k", "-XX:+UseSerialGC", "-XX:ActiveProcessorCount=1", "-XX:-UsePerfData")
NODE = ("/usr/bin/node", "--max-old-space-size=64", "--v8-pool-size=1")
LANGUAGES = MappingProxyType({item.id: item for item in (
    Language("python", "Python 3", ".py", "3.12.16", "python", "main.py", run_command=("/usr/local/bin/python", "-I", "-u", "/tmp/main.py")),
    Language("c", "C", ".c", "GCC 14.2.0", "native", "main.c", ("/usr/bin/gcc", "-std=c17", "-O0", "-fdiagnostics-color=never", "/tmp/main.c", "-o", "/tmp/program"), version_command=("/usr/bin/gcc", "-dumpfullversion"), version_prefix="14.2.0"),
    Language("cpp", "C++", ".cpp", "G++ 14.2.0", "native", "main.cpp", ("/usr/bin/g++", "-std=c++20", "-O0", "-fdiagnostics-color=never", "/tmp/main.cpp", "-o", "/tmp/program"), version_command=("/usr/bin/g++", "-dumpfullversion"), version_prefix="14.2.0"),
    Language("java", "Java", ".java", "OpenJDK 21.0.13", "java", "Main.java", ("/usr/bin/javac", *("-J"+arg for arg in JVM), "-encoding", "UTF-8", "-d", "/tmp", "/tmp/Main.java"), ("/usr/bin/java", *JVM, "-cp", "/tmp", "Main"), ("/usr/bin/javac", "-version"), "javac 21.0.13"),
    Language("javascript", "JavaScript", ".js", "Node.js 20.19.2 (Debian security maintained)", "node", "main.js", run_command=(*NODE, "/tmp/main.js"), version_command=("/usr/bin/node", "--version"), version_prefix="v20.19.2"),
    Language("typescript", "TypeScript", ".ts", "TypeScript 5.9.3 / Node.js 20.19.2", "node", "main.ts", (*NODE, "/usr/local/lib/node_modules/typescript/bin/tsc", "--target", "ES2020", "--module", "commonjs", "--strict", "--skipLibCheck", "--noEmitOnError", "--outDir", "/tmp/out", "/tmp/main.ts"), (*NODE, "/tmp/out/main.js"), (*NODE, "/usr/local/lib/node_modules/typescript/bin/tsc", "--version"), "Version 5.9.3"),
)})


def get_language(language):
    try:
        return LANGUAGES[language]
    except (KeyError, TypeError):
        raise ValueError("Unsupported language") from None


def image_for(settings, language):
    entry = get_language(language)
    if entry.family == "python":
        return PYTHON_IMAGE
    value = getattr(settings, "sandbox_" + entry.family + "_image", "") or ""
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", value):
        raise ValueError("Runtime image has not been provisioned")
    return value


def configuration(settings, language):
    entry = get_language(language)
    try:
        image = image_for(settings, language)
    except ValueError:
        image = None
    return {
        "language": language, "version": entry.version, "revision": RUNTIME_REVISION,
        "image": image, "recipe": asdict(entry),
        "memory_mb": settings.sandbox_memory_mb,
        "cpus": settings.sandbox_cpus, "pids": settings.sandbox_pids,
        "timeout": settings.sandbox_timeout,
        "compile_timeout": getattr(settings, "sandbox_compile_timeout", 10) if entry.compilation_required else 0,
        "output_bytes": settings.sandbox_output_bytes,
        "code_bytes": settings.sandbox_code_bytes, "stdin_bytes": 8192,
        "workspace_bytes": 16777216,
    }
