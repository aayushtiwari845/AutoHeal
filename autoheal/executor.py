"""Constrained subprocess execution. This is NOT an OS security sandbox."""
import ast
import ctypes
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time

MAX_CODE = 24000
MAX_OUTPUT = 16000
ALLOWED_MODULES = {"json", "math", "statistics", "collections", "re"}
ALLOWED_EXPORTS = {
    "json": {"dumps", "loads", "JSONDecodeError"},
    "math": {"ceil", "floor", "sqrt", "isfinite", "isnan", "isinf", "fsum", "factorial", "gcd", "lcm", "log", "log10", "log2", "exp", "sin", "cos", "tan", "radians", "degrees", "pi", "e", "tau", "inf", "nan", "prod", "isclose", "trunc", "fabs", "copysign", "hypot", "dist", "pow"},
    "statistics": {"mean", "fmean", "median", "median_low", "median_high", "mode", "multimode", "pstdev", "stdev", "pvariance", "variance", "quantiles", "StatisticsError"},
    "collections": {"Counter", "defaultdict", "deque", "OrderedDict"},
    "re": {"findall", "finditer", "match", "fullmatch", "search", "sub", "subn", "split", "escape", "IGNORECASE", "I", "MULTILINE", "M", "DOTALL", "S", "ASCII", "A"},
}
SAFE_BUILTINS = ["abs", "all", "any", "bool", "dict", "divmod", "enumerate", "filter", "float", "format", "frozenset", "int", "isinstance", "issubclass", "iter", "len", "list", "map", "max", "min", "next", "pow", "range", "repr", "reversed", "round", "set", "slice", "sorted", "str", "sum", "tuple", "zip", "Exception", "ArithmeticError", "AssertionError", "AttributeError", "IndexError", "KeyError", "LookupError", "NameError", "OverflowError", "RuntimeError", "StopIteration", "TypeError", "ValueError", "ZeroDivisionError"]
BLOCKED_NAMES = {"open", "exec", "eval", "compile", "getattr", "setattr", "delattr", "globals", "locals", "vars", "dir", "input", "breakpoint", "help", "exit", "quit", "memoryview", "object", "type", "super", "classmethod", "staticmethod", "property", "__import__"}
BLOCKED_ATTRIBUTES = {"open", "load", "dump", "system", "popen", "fork", "spawn", "exec", "eval", "compile", "exit", "kill", "remove", "unlink", "mkdir", "rmdir", "read", "write", "read_text", "write_text", "read_bytes", "write_bytes", "fileno", "format_map", "mro", "sys", "os", "builtins", "modules", "environ", "getenv", "codecs", "decoder", "encoder", "io"}


def inspect_code(code):
    if not isinstance(code, str) or not code.strip():
        return {"type": "CodePolicyError", "message": "No Python source was returned.", "line": None}
    if len(code) > MAX_CODE:
        return {"type": "CodePolicyError", "message": f"Source exceeds the {MAX_CODE}-character budget.", "line": None}
    try:
        tree = ast.parse(code, filename="<generated>")
    except SyntaxError as exc:
        return {"type": "SyntaxError", "message": exc.msg, "line": exc.lineno}
    module_aliases = {name: name for name in ALLOWED_MODULES}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module_aliases[alias.asname or alias.name] = alias.name
    for node in ast.walk(tree):
        problem = None
        if isinstance(node, ast.Import):
            if any(alias.name not in ALLOWED_MODULES for alias in node.names):
                problem = "Only json, math, statistics, collections, and re may be imported."
        elif isinstance(node, ast.ImportFrom):
            if node.level or node.module not in ALLOWED_MODULES or any(alias.name not in ALLOWED_EXPORTS.get(node.module, set()) for alias in node.names):
                problem = "Only explicit public imports from the approved modules are allowed."
        elif isinstance(node, ast.Name) and (node.id.startswith("_") or node.id in BLOCKED_NAMES):
            problem = f"Name {node.id!r} is unavailable in the constrained executor."
        elif isinstance(node, ast.Attribute) and (node.attr.startswith("_") or node.attr in BLOCKED_ATTRIBUTES):
            problem = f"Attribute {node.attr!r} is unavailable in the constrained executor."
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in module_aliases and node.attr not in ALLOWED_EXPORTS.get(module_aliases[node.value.id], set()):
            problem = f"Module export {node.attr!r} is outside the supported API."
        elif isinstance(node, (ast.ClassDef, ast.AsyncFunctionDef, ast.Await, ast.Global, ast.Nonlocal)):
            problem = f"{type(node).__name__} is outside the supported Python subset."
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
            # Format strings can traverse private attributes without AST nodes.
            problem = "Use f-strings or simple concatenation; str.format is disabled."
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and any(value in node.value for value in ("__class__", "__subclasses__", "__globals__", "__builtins__")):
            problem = "Runtime introspection strings are disallowed."
        if problem:
            return {"type": "CodePolicyError", "message": problem, "line": getattr(node, "lineno", None)}
    return None


def compact_output(value, limit=MAX_OUTPUT):
    """Bound output and compress adjacent repeated lines for useful feedback."""
    value = value.replace("\x00", "")
    lines = value.splitlines()
    result = []
    previous = None
    repeats = 0
    for line in lines:
        if line == previous:
            repeats += 1
            continue
        if repeats:
            result.append(f"[previous line repeated {repeats} times]")
        result.append(line)
        previous, repeats = line, 0
    if repeats:
        result.append(f"[previous line repeated {repeats} times]")
    joined = "\n".join(result)
    if len(joined) > limit:
        joined = joined[:limit] + "\n[output truncated]"
    return joined


def parse_error(stderr):
    lines = stderr.strip().splitlines()
    location = re.findall(r'File "<generated>", line (\d+)', stderr)
    last = lines[-1] if lines else "Python exited without a result."
    match = re.match(r"([A-Za-z][A-Za-z0-9_]*(?:Error|Exception)):\s*(.*)", last)
    return {"type": match.group(1) if match else "ExecutionError", "message": (match.group(2) if match else last)[:1000], "line": int(location[-1]) if location else None}


def _attach_job(process):
    """Best-effort Windows memory cap and child lifetime enforcement."""
    if os.name != "nt":
        return None
    from ctypes import wintypes

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class BASIC(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong), ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD), ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

    class EXTENDED(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO_COUNTERS), ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        return None
    limits = EXTENDED()
    # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | PROCESS_MEMORY | ACTIVE_PROCESS
    limits.BasicLimitInformation.LimitFlags = 0x2000 | 0x0100 | 0x0008
    limits.BasicLimitInformation.ActiveProcessLimit = 1
    limits.ProcessMemoryLimit = 384 * 1024 * 1024
    if not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)) or not kernel.AssignProcessToJobObject(job, wintypes.HANDLE(int(process._handle))):
        kernel.CloseHandle(job)
        return None
    return (kernel, job)


def _harness(code, data):
    return "\n".join([
        "import builtins, json, math, statistics, collections, re, sys",
        "_modules = {name: globals()[name] for name in ('json', 'math', 'statistics', 'collections', 're')}",
        f"_safe = {{name: getattr(builtins, name) for name in {SAFE_BUILTINS!r}}}",
        "def _import(name, globals=None, locals=None, fromlist=(), level=0):",
        "    if level or name not in _modules: raise ImportError('Import is not allowed')",
        "    return _modules[name]",
        "_printed = 0",
        "def _print(*values, sep=' ', end='\\n'):",
        "    global _printed",
        "    text = sep.join(str(value) for value in values) + end",
        "    _printed += len(text)",
        f"    if _printed > {MAX_OUTPUT}: raise RuntimeError('Output budget exceeded')",
        "    builtins.print(text, end='', flush=True)",
        "_safe['print'] = _print",
        "_safe['__import__'] = _import",
        f"_env = {{'__builtins__': _safe, 'DATA': json.loads({json.dumps(data)!r}), 'json': json}}",
        f"_code = {code!r}",
        "_compiled = compile(_code, '<generated>', 'exec')",
        "def _audit(event, args):",
        "    if event == 'open' or event == 'import' or event.startswith(('os.', 'socket.', 'subprocess.', 'ctypes.', 'shutil.')):",
        "        raise PermissionError('Filesystem, network, process, and native calls are denied')",
        "sys.addaudithook(_audit)",
        "exec(_compiled, _env, _env)",
    ])


def execute_code(code, data, timeout=5, cancel_event=None):
    started = time.monotonic()
    error = inspect_code(code)
    base = {"stdout": "", "stderr": "", "returncode": None, "duration_ms": 0, "error": error, "output": None, "job_limit_active": False}
    if error:
        base["stderr"] = f"{error['type']}: {error['message']}"
        return base
    timeout = max(1.0, min(float(timeout), 5.0))
    with tempfile.TemporaryDirectory(prefix="autoheal-run-") as directory:
        path = Path(directory) / "runner.py"
        path.write_text(_harness(code, data), encoding="utf-8")
        # An allowlist ensures provider keys and unrelated environment secrets
        # never enter the generated-program process.
        env = {name: os.environ[name] for name in ("SYSTEMROOT", "WINDIR", "COMSPEC") if name in os.environ}
        env.update({"TEMP": directory, "TMP": directory, "PYTHONIOENCODING": "utf-8"})
        process = subprocess.Popen([sys.executable, "-I", "-S", "-X", "utf8", str(path)], cwd=directory, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        job = _attach_job(process)
        base["job_limit_active"] = bool(job)
        buffers = {"stdout": bytearray(), "stderr": bytearray()}
        over_budget = threading.Event()

        def drain(stream, target):
            try:
                while True:
                    chunk = stream.read(4096)
                    if not chunk:
                        return
                    remaining = MAX_OUTPUT + 4096 - len(buffers[target])
                    if remaining > 0:
                        buffers[target].extend(chunk[:remaining])
                    if remaining < len(chunk):
                        over_budget.set()
                        return
            except (OSError, ValueError):
                return

        threads = [threading.Thread(target=drain, args=(getattr(process, target), target), daemon=True) for target in buffers]
        for thread in threads:
            thread.start()
        termination = None
        while process.poll() is None:
            if cancel_event and cancel_event.is_set():
                termination = {"type": "Cancelled", "message": "Execution cancelled by the user.", "line": None}
            elif over_budget.is_set():
                termination = {"type": "OutputLimitError", "message": "Output exceeded the bounded capture budget.", "line": None}
            elif time.monotonic() - started >= timeout:
                termination = {"type": "TimeoutError", "message": f"Execution exceeded {timeout:g} seconds.", "line": None}
            if termination:
                process.kill()
                break
            time.sleep(0.015)
        process.wait(timeout=3)
        for thread in threads:
            thread.join(timeout=1)
        process.stdout.close()
        process.stderr.close()
        if job:
            job[0].CloseHandle(job[1])
        stdout = buffers["stdout"].decode("utf-8", "replace")
        stderr = buffers["stderr"].decode("utf-8", "replace").replace(directory, "<temporary workspace>")
        base.update(stdout=compact_output(stdout), stderr=compact_output(stderr), returncode=process.returncode, duration_ms=round((time.monotonic() - started) * 1000), error=termination)
        if not base["error"] and process.returncode != 0:
            base["error"] = parse_error(stderr)
        if not base["error"]:
            try:
                def reject_constant(value):
                    raise ValueError(f"Non-finite JSON value {value!r}")
                def finite_float(value):
                    parsed = float(value)
                    if not math.isfinite(parsed):
                        raise ValueError(f"Non-finite JSON number {value!r}")
                    return parsed
                def unique_keys(pairs):
                    result = {}
                    for key, value in pairs:
                        if key in result:
                            raise ValueError(f"Duplicate JSON key {key!r}")
                        result[key] = value
                    return result
                base["output"] = json.loads(stdout.strip(), parse_constant=reject_constant, parse_float=finite_float, object_pairs_hook=unique_keys)
            except (ValueError, RecursionError) as exc:
                base["error"] = {"type": "OutputFormatError", "message": f"Print exactly one valid JSON value: {str(exc)[:500]}", "line": None}
        return base
