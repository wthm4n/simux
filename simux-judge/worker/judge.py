import pika
import docker
import json
import time
import psycopg2
import os
import tempfile
import shutil
import threading
import sys
import itertools
from flask import Flask, request, jsonify
from dotenv import load_dotenv

# ── Load env ──────────────────────────────────────────────────────────────────
_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_dir, '.env'))

# ── Seccomp profile path ──────────────────────────────────────────────────────
# Auto-resolves to ../sandbox/seccomp.json relative to this file (worker/judge.py).
# Override by setting SECCOMP_PROFILE_PATH in worker/.env — use an absolute path.
# If the env var is set to the old placeholder value, ignore it and use the default.
_env_seccomp = os.environ.get("SECCOMP_PROFILE_PATH", "")
_default_seccomp = os.path.normpath(os.path.join(_dir, "..", "sandbox", "seccomp.json"))

if _env_seccomp and "absolute/path/to" not in _env_seccomp:
    SECCOMP_PROFILE_PATH = _env_seccomp
else:
    SECCOMP_PROFILE_PATH = _default_seccomp

# Hard cap on container stdout — 10 MB
MAX_OUTPUT_BYTES = 10 * 1024 * 1024


# ─────────────────────────────────────────────────────────────────────────────
# Terminal display helpers (unchanged)
# ─────────────────────────────────────────────────────────────────────────────

class C:
    RESET   = "\033[0m";  BOLD    = "\033[1m";  DIM     = "\033[2m"
    RED     = "\033[31m"; GREEN   = "\033[32m"; YELLOW  = "\033[33m"
    CYAN    = "\033[36m"; WHITE   = "\033[37m"; MAGENTA = "\033[35m"
    BG_RED  = "\033[41m"; BG_GREEN = "\033[42m"; BG_YELLOW = "\033[43m"
    BG_MAGENTA = "\033[45m"
    BRIGHT_RED    = "\033[91m"; BRIGHT_GREEN  = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"; BRIGHT_BLUE   = "\033[94m"
    BRIGHT_CYAN   = "\033[96m"; BRIGHT_WHITE  = "\033[97m"
    BRIGHT_MAGENTA = "\033[95m"

def _c(text, *codes): return "".join(codes) + str(text) + C.RESET
def _divider(char="─", width=64, color=C.DIM): return _c(char * width, color)
def _timestamp(): return time.strftime("%H:%M:%S")

def _header(text):
    pad = (62 - len(text)) // 2
    line = " " * pad + text + " " * pad
    print(_c("┌" + "─" * 64 + "┐", C.DIM, C.CYAN))
    print(_c("│", C.DIM, C.CYAN) + _c(f" {line[:62]:62} ", C.BOLD, C.BRIGHT_WHITE) + _c("│", C.DIM, C.CYAN))
    print(_c("└" + "─" * 64 + "┘", C.DIM, C.CYAN))

def _section(label, icon="◆"):
    print(f"\n{_c(icon, C.CYAN)} {_c(label, C.BOLD, C.BRIGHT_WHITE)}")
    print(_divider())

def _log(level, msg):
    icons = {"info": ("·", C.BRIGHT_BLUE), "ok": ("✔", C.BRIGHT_GREEN),
             "warn": ("⚠", C.BRIGHT_YELLOW), "error": ("✖", C.BRIGHT_RED), "dim": ("·", C.DIM)}
    icon, color = icons.get(level, ("·", C.RESET))
    print(f"  {_c(f'[{_timestamp()}]', C.DIM)} {_c(icon, color)}  {msg}")


class Spinner:
    FRAMES = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]
    def __init__(self, label):
        self.label = label
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._spin, daemon=True)
    def _spin(self):
        for frame in itertools.cycle(self.FRAMES):
            if self._stop.is_set(): break
            sys.stdout.write(f"\r  {_c(frame, C.BRIGHT_CYAN)}  {_c(self.label, C.DIM)}   ")
            sys.stdout.flush()
            time.sleep(0.08)
        sys.stdout.write("\r" + " " * (len(self.label) + 12) + "\r")
        sys.stdout.flush()
    def start(self): self._thread.start(); return self
    def stop(self, ok=True, final_msg=None):
        self._stop.set(); self._thread.join()
        icon = _c("✔", C.BRIGHT_GREEN) if ok else _c("✖", C.BRIGHT_RED)
        print(f"  {icon}  {final_msg or self.label}")
    def __enter__(self): self.start(); return self
    def __exit__(self, exc_type, *_): self.stop(ok=(exc_type is None))


VERDICT_META = {
    "AC":  {"label": "Accepted",             "desc": "All test cases passed.",                   "icon": "✔", "color": C.BRIGHT_GREEN,   "bg": C.BG_GREEN},
    "WA":  {"label": "Wrong Answer",         "desc": "Output did not match expected output.",    "icon": "✖", "color": C.BRIGHT_RED,     "bg": C.BG_RED},
    "TLE": {"label": "Time Limit Exceeded",  "desc": "Program took longer than the limit.",      "icon": "⧖", "color": C.BRIGHT_YELLOW,  "bg": C.BG_YELLOW},
    "RE":  {"label": "Runtime Error",        "desc": "Program crashed or exited non-zero.",      "icon": "⚡", "color": C.BRIGHT_RED,     "bg": C.BG_RED},
    "CE":  {"label": "Compile Error",        "desc": "Compilation failed — check your syntax.",  "icon": "⚒", "color": C.BRIGHT_YELLOW,  "bg": C.BG_YELLOW},
    "SE":  {"label": "System Error",         "desc": "Internal judge error — please resubmit.", "icon": "⚙", "color": C.BRIGHT_MAGENTA, "bg": C.BG_MAGENTA},
    "MLE": {"label": "Memory Limit Exceeded","desc": "Program exceeded memory limit.",           "icon": "◈", "color": C.BRIGHT_RED,     "bg": C.BG_RED},
    "OLE": {"label": "Output Limit Exceeded","desc": "Program produced too much output.",        "icon": "◉", "color": C.BRIGHT_RED,     "bg": C.BG_RED},
}

def _verdict_banner(verdict_code):
    meta = VERDICT_META.get(verdict_code, {"label": verdict_code, "desc": "", "icon": "?", "color": C.WHITE, "bg": ""})
    width = 64
    bar   = "━" * width
    inner = f"  {meta['icon']}  {meta['label']}"
    print(f"\n{_c(bar, meta['color'])}")
    print(_c(f"  {inner:<{width - 2}}", C.BOLD, meta['color']))
    if meta["desc"]: print(_c(f"  {meta['desc']:<{width - 2}}", meta['color']))
    print(_c(bar, meta['color']))

def _test_table(test_cases_results):
    COL = [6, 10, 22, 16, 16, 9]
    HEADERS = ["Test", "Status", "Input", "Expected", "Got", "Time"]
    STATUS_STYLE = {
        "pass":  ("Passed",      C.BRIGHT_GREEN),
        "fail":  ("Wrong ans.",  C.BRIGHT_RED),
        "tle":   ("Time limit",  C.BRIGHT_YELLOW),
        "error": ("Runtime err", C.BRIGHT_RED),
        "skip":  ("Skipped",     C.DIM),
        "ole":   ("Output lim.", C.BRIGHT_RED),
    }
    def _cell(text, width):
        s = str(text)
        return (s[:width-5] + "…").ljust(width) if len(s) > width-2 else s.ljust(width)
    def _row(cells, colors=None):
        colors = colors or [C.RESET]*len(cells)
        parts = [_c(_cell(c, w), col) for (c, w), col in zip(zip(cells, COL), colors)]
        return _c("│", C.DIM) + _c("│", C.DIM).join(parts) + _c("│", C.DIM)
    def _row_sep(l="├", m="┼", r="┤", b="─"):
        return _c(l, C.DIM) + _c(m.join(b*w for w in COL), C.DIM) + _c(r, C.DIM)

    print(_c("┌" + "┬".join("─"*w for w in COL) + "┐", C.DIM))
    print(_row(HEADERS, [C.BOLD]*len(HEADERS)))
    print(_row_sep())
    for i, t in enumerate(test_cases_results):
        sl, sc = STATUS_STYLE.get(t["status"], (t["status"], C.WHITE))
        time_str = f"{t['time_ms']} ms" if t["time_ms"] > 0 else "—"
        tc = C.BRIGHT_YELLOW if t["time_ms"] > 1500 else C.DIM
        gc = C.BRIGHT_GREEN if t["status"] == "pass" else C.BRIGHT_RED
        print(_row([f"  #{t['n']}", f"  {sl}", f"  {t.get('input','')!r}",
                    f"  {t.get('expected','—')}", f"  {t.get('got','—')}", f"  {time_str}"],
                   [C.WHITE, sc, C.DIM, C.DIM, gc if t["status"] in ("pass","fail") else C.DIM, tc]))
        if t.get("stderr"):
            preview = t["stderr"].strip().replace("\n"," | ")[:120]
            print(_c("│", C.DIM) + _c(f"  ↳ stderr: {preview}".ljust(sum(COL)), C.BRIGHT_RED) + _c("│", C.DIM))
        if i < len(test_cases_results)-1: print(_row_sep("├","┼","┤","─"))
    print(_c("└" + "┴".join("─"*w for w in COL) + "┘", C.DIM))

def _summary_row(submission_id, language, verdict_code, passed, total, time_ms):
    meta = VERDICT_META.get(verdict_code, {"color": C.WHITE, "label": verdict_code})
    print(
        f"\n  {_c('ID', C.DIM)}      {_c(submission_id, C.BOLD)}"
        f"\n  {_c('Language', C.DIM)} {_c(language, C.BRIGHT_CYAN)}"
        f"\n  {_c('Result', C.DIM)}   {_c(meta['label'], C.BOLD, meta['color'])}"
        f"\n  {_c('Tests', C.DIM)}    {_c(f'{passed}/{total} passed', C.BRIGHT_GREEN if passed==total else C.BRIGHT_RED)}"
        f"\n  {_c('Time', C.DIM)}     {_c(f'{time_ms} ms', C.DIM)}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# DB
# ─────────────────────────────────────────────────────────────────────────────

def get_db():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        database=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        port=int(os.environ.get("DB_PORT", 5432)),
    )

def setup_db():
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS submissions (
            id TEXT PRIMARY KEY,
            language TEXT,
            code TEXT,
            status TEXT DEFAULT 'pending',
            verdict TEXT,
            stdout TEXT,
            stderr TEXT,
            time_ms INTEGER,
            memory_kb INTEGER,
            test_results JSONB,
            problem_id INTEGER,
            user_id INTEGER,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    # Add columns that may be missing on older installs
    for col, typ in [("test_results", "JSONB"), ("memory_kb", "INTEGER")]:
        cur.execute(f"ALTER TABLE submissions ADD COLUMN IF NOT EXISTS {col} {typ}")
    conn.commit()
    cur.close()
    conn.close()
    _log("ok", "Database schema verified.")


# ─────────────────────────────────────────────────────────────────────────────
# Language config
# ─────────────────────────────────────────────────────────────────────────────

LANGUAGE_CONFIG = {
    # ── Interpreted — no compile stage, no syntax-check container.
    #    Syntax errors surface as RE with a readable traceback from the runtime.
    #    A separate py_compile / node --check container costs a full spawn for
    #    zero benefit over letting the runtime reject it on the first test case.
    "python": {
        "image":       "python:3.11-slim",
        "filename":    "solution.py",
        "compile_cmd": None,
        "exec_cmd":    "python -u /code/solution.py < /code/input.txt",
    },
    "javascript": {
        "image":       "node:20-slim",
        "filename":    "solution.js",
        "compile_cmd": None,
        "exec_cmd":    "node --max-old-space-size=200 /code/solution.js < /code/input.txt",
    },

    # ── Compiled — compile_cmd runs once; exec_cmd runs per test case. ────────
    "c": {
        "image":       "gcc:13",
        "filename":    "solution.c",
        "compile_cmd": "gcc /code/solution.c -o /code/solution -O2 -lm 2>&1",
        "exec_cmd":    "/code/solution < /code/input.txt",
    },
    "cpp": {
        "image":       "gcc:13",
        "filename":    "solution.cpp",
        "compile_cmd": "g++ /code/solution.cpp -o /code/solution -O2 -std=c++17 2>&1",
        "exec_cmd":    "/code/solution < /code/input.txt",
    },
    "java": {
        "image":       "eclipse-temurin:21-jdk-alpine",
        "filename":    "Main.java",
        "compile_cmd": "javac /code/Main.java 2>&1",
        "exec_cmd":    "java -cp /code -Xmx200m Main < /code/input.txt",
    },
    "rust": {
        "image":       "rust:1.78-slim",
        "filename":    "solution.rs",
        "compile_cmd": "rustc /code/solution.rs -o /code/solution --edition 2021 2>&1",
        "exec_cmd":    "/code/solution < /code/input.txt",
    },
}

COMPILE_TIMEOUT_S  = 30   # wall-clock for the compile container
DEFAULT_TIMEOUT_S  = 10   # wall-clock per test-case execution container


# ─────────────────────────────────────────────────────────────────────────────
# Seccomp loader
# ─────────────────────────────────────────────────────────────────────────────

# Cached at module load time — read once, reused for every container run.
# This also means the warning only prints once at startup, not per submission.
def _build_security_opts_once() -> list[str]:
    path = os.path.abspath(SECCOMP_PROFILE_PATH)
    opts = ["no-new-privileges"]
    if not os.path.exists(path):
        _log("warn", f"seccomp.json not found at {path} — using Docker default seccomp")
        return opts
    try:
        with open(path) as f:
            profile = f.read()
        _log("ok", f"Seccomp profile loaded  → {path}")
        opts.append(f"seccomp={profile}")
    except Exception as e:
        _log("warn", f"Failed to load seccomp: {e} — using Docker default")
    return opts

# Build once at import time
_SECURITY_OPTS: list[str] = _build_security_opts_once()


# ─────────────────────────────────────────────────────────────────────────────
# Hardened Docker runner
#
# Security flags applied to EVERY container:
#   network_disabled  — no outbound network
#   mem_limit         — 256 MB RAM hard cap
#   memswap_limit     — equal to mem_limit → no swap
#   cpu_quota         — 50% of one CPU core
#   pids_limit        — 64 processes max (prevents fork bombs)
#   read_only         — root filesystem is read-only
#   tmpfs /tmp        — 64 MB writable scratch for runtimes that need it
#   user nobody       — runs as uid 65534, not root
#   cap_drop ALL      — all Linux capabilities dropped
#   security_opt      — no-new-privileges + custom seccomp whitelist
#   ulimits           — 64 MB stack/fsize, no core dumps, 64 fds
#   stdout cap        — OLE verdict if output > 10 MB
#   logs before rm    — container.logs() called BEFORE container.remove()
# ─────────────────────────────────────────────────────────────────────────────

def _build_security_opts() -> list[str]:
    return _SECURITY_OPTS


def _run_container_blocking(
    client,
    image:      str,
    command:    str,
    tmp_dir:    str,
    wall_limit: int,
    label:      str,
    *,
    # extra_ulimits lets callers add ulimits on top of the base set
    extra_ulimits: list | None = None,
) -> dict:
    """
    Shared low-level harness used by both compile_in_docker and run_in_docker.

    Returns a dict with keys:
        stdout   str   — captured stdout (capped at MAX_OUTPUT_BYTES)
        stderr   str   — error text on non-zero exit, else ""
        time_ms  int   — wall-clock ms from thread start to join
        error    str|None — None | "runtime_error" | "system_error"
        tle      bool
        ole      bool
        oom      bool  — True if Docker reports OOMKilled
    """
    result_holder: dict = {}
    full_cmd = f'sh -c "{command}"'

    base_ulimits = [
        docker.types.Ulimit(name="stack",  soft=67108864, hard=67108864),
        docker.types.Ulimit(name="fsize",  soft=67108864, hard=67108864),
        docker.types.Ulimit(name="core",   soft=0,        hard=0),
        docker.types.Ulimit(name="nofile", soft=64,       hard=64),
        docker.types.Ulimit(name="nproc",  soft=64,       hard=64),
    ]
    ulimits = base_ulimits + (extra_ulimits or [])

    def _run():
        try:
            raw: bytes = client.containers.run(
                image=image,
                command=full_cmd,
                volumes={tmp_dir: {"bind": "/code", "mode": "rw"}},
                read_only=True,
                tmpfs={"/tmp": "size=64m,mode=1777"},
                network_disabled=True,
                mem_limit="256m",
                memswap_limit="256m",
                cpu_quota=50000,
                cpu_period=100000,
                pids_limit=64,
                user="65534:65534",
                cap_drop=["ALL"],
                security_opt=_build_security_opts(),
                ulimits=ulimits,
                stdout=True,
                stderr=False,
                remove=True,
                detach=False,
            )
            ole    = len(raw) > MAX_OUTPUT_BYTES
            stdout = raw[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace").strip()
            result_holder["result"] = {"stdout": stdout, "exit_code": 0, "ole": ole}

        except docker.errors.ContainerError as e:
            raw_err      = e.stderr if e.stderr else b""
            stderr_clean = raw_err.decode("utf-8", errors="replace").strip()
            if stderr_clean in ("Killed", "") and not stderr_clean.startswith("/"):
                result_holder["ole"] = True
            else:
                result_holder["runtime_error"] = stderr_clean[:65536]

        except Exception as exc:
            result_holder["exception"] = exc

    spinner = Spinner(label)
    spinner.start()
    t0     = time.time()
    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=wall_limit)
    elapsed = int((time.time() - t0) * 1000)

    if thread.is_alive():
        spinner.stop(ok=False, final_msg=f"Timed out after {wall_limit}s — killing…")
        _kill_orphan_containers(client, tmp_dir)
        return {"stdout": "", "stderr": "", "time_ms": elapsed,
                "error": None, "tle": True, "ole": False, "oom": False}

    if "exception" in result_holder:
        spinner.stop(ok=False, final_msg="Unexpected exception.")
        raise result_holder["exception"]

    if result_holder.get("ole"):
        spinner.stop(ok=False, final_msg=f"Output limit exceeded ({elapsed} ms)")
        return {"stdout": "", "stderr": "Output limit exceeded", "time_ms": elapsed,
                "error": None, "tle": False, "ole": True, "oom": False}

    if "runtime_error" in result_holder:
        stderr = result_holder["runtime_error"]
        spinner.stop(ok=False, final_msg=f"Non-zero exit ({elapsed} ms)")
        _log("error", f"stderr: {stderr[:200]}")
        return {"stdout": "", "stderr": stderr, "time_ms": elapsed,
                "error": "runtime_error", "tle": False, "ole": False, "oom": False}

    r = result_holder.get("result", {})
    if r.get("ole"):
        spinner.stop(ok=False, final_msg=f"Output limit exceeded ({elapsed} ms)")
        return {"stdout": "", "stderr": "Output limit exceeded (>10 MB)", "time_ms": elapsed,
                "error": None, "tle": False, "ole": True, "oom": False}

    spinner.stop(ok=True, final_msg=f"{label.split('(')[0].strip()} — {elapsed} ms")
    return {
        "stdout":  r.get("stdout", ""),
        "stderr":  "",
        "time_ms": elapsed,
        "error":   None,
        "tle":     False,
        "ole":     False,
        "oom":     False,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — Compile
#
# Runs the compiler once per submission and writes the binary into tmp_dir.
# Returns a verdict dict:
#   {"ok": True}
#   {"ok": False, "verdict": "CE", "stderr": "...compiler output..."}
#   {"ok": False, "verdict": "SE", "stderr": "..."}
# ─────────────────────────────────────────────────────────────────────────────

def compile_in_docker(language: str, tmp_dir: str) -> dict:
    """
    Compile the source already written into tmp_dir.
    Interpreted languages (compile_cmd=None) skip this entirely — returns ok immediately.
    For compiled languages this produces the binary consumed by run_test_in_docker.
    """
    cfg         = LANGUAGE_CONFIG[language]
    compile_cmd = cfg.get("compile_cmd")

    # ── Interpreted: nothing to compile, skip ────────────────────────────────
    if compile_cmd is None:
        return {"ok": True, "compile_ms": 0}

    # ── Compiled: run the compiler once ──────────────────────────────────────
    client     = docker.from_env()
    wall_limit = COMPILE_TIMEOUT_S
    label      = f"Compiling {language}  (wall: {wall_limit}s)…"
    _log("info", label)

    try:
        result = _run_container_blocking(
            client, cfg["image"], compile_cmd, tmp_dir, wall_limit, label,
        )
    except Exception as e:
        _log("error", f"Compile stage SE: {e}")
        return {"ok": False, "verdict": "SE", "stderr": str(e)}

    if result["tle"]:
        return {"ok": False, "verdict": "CE",
                "stderr": f"Compilation timed out after {wall_limit}s"}

    if result["error"] == "runtime_error":
        # Compiler exited non-zero → CE.
        # compile_cmd uses 2>&1 so compiler error text is in stdout.
        compiler_output = result["stdout"] or result["stderr"]
        _log("warn", f"CE: {compiler_output[:200]}")
        return {"ok": False, "verdict": "CE", "stderr": compiler_output}

    if result["error"] == "system_error":
        return {"ok": False, "verdict": "SE", "stderr": result["stderr"]}

    _log("ok", f"Compiled in {result['time_ms']} ms")
    return {"ok": True, "compile_ms": result["time_ms"]}


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — Execute one test case
#
# The binary / source is already in tmp_dir from Stage 1.
# Timing starts HERE — compile time is NOT included.
# ─────────────────────────────────────────────────────────────────────────────

def run_in_docker(language: str, code: str, stdin_input: str = "") -> dict:
    """
    Public API kept identical to the old signature so /execute endpoint
    (used by /run) continues to work unchanged.

    For /run (sample cases only) this is called without pre-compilation,
    so we still do compile+run in sequence inside a single tmp_dir.
    The judge() function bypasses this and calls compile_in_docker once
    then run_test_in_docker per test case.
    """
    cfg = LANGUAGE_CONFIG.get(language)
    if cfg is None:
        _log("error", f"Unsupported language: '{language}'")
        return {"stdout": "", "stderr": f"unsupported language: '{language}'",
                "time_ms": 0, "error": "system_error"}

    tmp_dir = tempfile.mkdtemp()
    os.chmod(tmp_dir, 0o777)

    try:
        src_path   = os.path.join(tmp_dir, cfg["filename"])
        input_path = os.path.join(tmp_dir, "input.txt")

        with open(src_path,   "w") as f: f.write(code)
        with open(input_path, "w") as f: f.write(stdin_input)
        os.chmod(src_path,   0o666)
        os.chmod(input_path, 0o666)

        _log("dim", f"Sandbox mount  → {tmp_dir}")

        # ── Compile / syntax-check ────────────────────────────────────────
        compile_result = compile_in_docker(language, tmp_dir)
        if not compile_result["ok"]:
            verdict = compile_result["verdict"]   # "CE" or "SE"
            stderr  = compile_result["stderr"]
            return {"stdout": "", "stderr": stderr, "time_ms": 0,
                    "error": "compile_error" if verdict == "CE" else "system_error",
                    "verdict": verdict}

        # ── Execute ───────────────────────────────────────────────────────
        return run_test_in_docker(language, tmp_dir, stdin_input, auto_cleanup=False)

    except Exception as e:
        _log("error", f"SYSTEM ERROR  {type(e).__name__}: {e}")
        return {"stdout": "", "stderr": str(e), "time_ms": 0, "error": "system_error"}

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def run_test_in_docker(
    language:     str,
    tmp_dir:      str,
    stdin_input:  str = "",
    *,
    time_limit_ms: int  = 0,     # 0 = use DEFAULT_TIMEOUT_S
    auto_cleanup: bool  = True,  # set False when caller owns tmp_dir lifetime
) -> dict:
    """
    Execute the already-compiled binary / source for one test case.
    tmp_dir must already contain the compiled artifact and will receive input.txt.
    Timing is wall-clock of this container ONLY — no compile time.
    """
    cfg        = LANGUAGE_CONFIG[language]
    client     = docker.from_env()
    exec_cmd   = cfg["exec_cmd"]
    wall_limit = (time_limit_ms // 1000 + 2) if time_limit_ms else DEFAULT_TIMEOUT_S

    try:
        input_path = os.path.join(tmp_dir, "input.txt")
        with open(input_path, "w") as f:
            f.write(stdin_input)
        os.chmod(input_path, 0o666)

        label  = f"Executing {language}  (wall: {wall_limit}s)…"
        result = _run_container_blocking(
            client, cfg["image"], exec_cmd, tmp_dir, wall_limit, label,
        )
        return result

    except Exception as e:
        _log("error", f"SYSTEM ERROR run_test  {type(e).__name__}: {e}")
        return {"stdout": "", "stderr": str(e), "time_ms": 0,
                "error": "system_error", "tle": False, "ole": False, "oom": False}

    finally:
        if auto_cleanup:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def _kill_orphan_containers(client, tmp_dir: str):
    """Kill any containers that are still mounted on our tmpdir."""
    try:
        for c in client.containers.list():
            mounts = str(c.attrs.get("Mounts", ""))
            if tmp_dir in mounts or os.path.basename(tmp_dir) in mounts:
                _log("warn", f"Killing orphan container {c.short_id}")
                c.kill()
                try:
                    c.remove(force=True)
                except Exception:
                    pass
    except Exception as kill_err:
        _log("warn", f"Kill error: {kill_err}")


# ─────────────────────────────────────────────────────────────────────────────
# Judge — per-test breakdown with OLE verdict support
# ─────────────────────────────────────────────────────────────────────────────

def judge(submission_id: str, language: str, code: str, test_cases: list) -> dict:
    _section(f"Judging  {submission_id}  ({language})", "◈")

    display_rows = []
    test_results = []
    passed       = 0
    result       = {}   # last test result, used for final time_ms

    def _skip_remaining(from_idx: int, verdict_code: str):
        for j in range(from_idx, len(test_cases)):
            display_rows.append({
                "n": j+1, "status": "skip",
                "input": test_cases[j]["input"],
                "expected": test_cases[j].get("expected_output",""),
                "got": "—", "time_ms": 0,
            })
            test_results.append({
                "n": j+1, "passed": False, "verdict": "skip",
                "time_ms": 0, "actual_output": "", "stderr": "",
                "is_sample": test_cases[j].get("is_sample", False),
            })

    # ── Stage 1: Compile once ─────────────────────────────────────────────────
    # Source lands in tmp_dir; compiled binary stays there for all test cases.
    cfg     = LANGUAGE_CONFIG.get(language)
    if cfg is None:
        _log("error", f"Unsupported language: '{language}'")
        return {"verdict": "SE", "time_ms": 0, "test_results": []}

    tmp_dir  = tempfile.mkdtemp()
    os.chmod(tmp_dir, 0o777)

    src_path = os.path.join(tmp_dir, cfg["filename"])
    with open(src_path, "w") as f:
        f.write(code)
    os.chmod(src_path, 0o666)

    compile_result = compile_in_docker(language, tmp_dir)

    if not compile_result["ok"]:
        verdict = compile_result["verdict"]   # "CE" or "SE"
        stderr  = compile_result["stderr"]
        shutil.rmtree(tmp_dir, ignore_errors=True)
        for j, tc in enumerate(test_cases):
            test_results.append({
                "n": j+1, "passed": False, "verdict": verdict,
                "time_ms": 0, "actual_output": "", "stderr": stderr,
                "is_sample": tc.get("is_sample", False),
            })
        _verdict_banner(verdict)
        _log("warn" if verdict == "CE" else "error", f"{verdict}: {stderr[:300]}")
        _summary_row(submission_id, language, verdict, 0, len(test_cases), 0)
        return {"verdict": verdict, "stderr": stderr, "time_ms": 0,
                "test_results": test_results}

    compile_ms = compile_result.get("compile_ms", 0)
    _log("ok", f"Compiled in {compile_ms} ms — running {len(test_cases)} test case(s)")

    # ── Stage 2: Execute each test case ──────────────────────────────────────
    try:
        for i, tc in enumerate(test_cases):
            n         = i + 1
            result    = run_test_in_docker(language, tmp_dir, tc["input"],
                                           auto_cleanup=False)
            is_sample = tc.get("is_sample", False)

            # ── Output Limit Exceeded ─────────────────────────────────────
            if result.get("ole"):
                display_rows.append({"n": n, "status": "ole", "input": tc["input"],
                                      "expected": tc.get("expected_output",""), "got": "[truncated]", "time_ms": result["time_ms"]})
                test_results.append({"n": n, "passed": False, "verdict": "OLE",
                                      "time_ms": result["time_ms"], "actual_output": "", "stderr": "Output limit exceeded",
                                      "is_sample": is_sample})
                _skip_remaining(i+1, "OLE")
                _test_table(display_rows); _verdict_banner("OLE")
                _summary_row(submission_id, language, "OLE", passed, len(test_cases), result["time_ms"])
                return {"verdict": "OLE", "test": n, "time_ms": result["time_ms"], "test_results": test_results}

            # ── TLE (wall-clock timeout) ──────────────────────────────────
            if result.get("tle"):
                display_rows.append({"n": n, "status": "tle", "input": tc["input"],
                                      "expected": tc.get("expected_output",""), "got": "—", "time_ms": result["time_ms"]})
                test_results.append({"n": n, "passed": False, "verdict": "TLE",
                                      "time_ms": result["time_ms"], "actual_output": "", "stderr": "",
                                      "is_sample": is_sample})
                _skip_remaining(i+1, "TLE")
                _test_table(display_rows); _verdict_banner("TLE")
                _summary_row(submission_id, language, "TLE", passed, len(test_cases), result["time_ms"])
                return {"verdict": "TLE", "test": n, "time_ms": result["time_ms"], "test_results": test_results}

            # ── OOM killed → MLE ──────────────────────────────────────────
            if result.get("oom"):
                display_rows.append({"n": n, "status": "error", "input": tc["input"],
                                      "expected": tc.get("expected_output",""), "got": "—", "time_ms": result["time_ms"]})
                test_results.append({"n": n, "passed": False, "verdict": "MLE",
                                      "time_ms": result["time_ms"], "actual_output": "",
                                      "stderr": "Memory limit exceeded", "is_sample": is_sample})
                _skip_remaining(i+1, "MLE")
                _test_table(display_rows); _verdict_banner("MLE")
                _summary_row(submission_id, language, "MLE", passed, len(test_cases), result["time_ms"])
                return {"verdict": "MLE", "test": n, "time_ms": result["time_ms"], "test_results": test_results}

            # ── System error ──────────────────────────────────────────────
            if result.get("error") == "system_error":
                _log("error", f"System error on test #{n}: {result['stderr'][:200]}")
                _verdict_banner("SE")
                test_results.append({"n": n, "passed": False, "verdict": "SE",
                                      "time_ms": 0, "actual_output": "", "stderr": result.get("stderr",""),
                                      "is_sample": is_sample})
                return {"verdict": "SE", "detail": result["stderr"], "test_results": test_results}

            # ── Runtime error ─────────────────────────────────────────────
            if result.get("error") == "runtime_error":
                display_rows.append({"n": n, "status": "error", "input": tc["input"],
                                      "expected": tc.get("expected_output",""), "got": "—",
                                      "time_ms": result["time_ms"], "stderr": result["stderr"]})
                test_results.append({"n": n, "passed": False, "verdict": "RE",
                                      "time_ms": result["time_ms"], "actual_output": "",
                                      "stderr": result.get("stderr",""), "is_sample": is_sample})
                _skip_remaining(i+1, "RE")
                _test_table(display_rows); _verdict_banner("RE")
                _summary_row(submission_id, language, "RE", passed, len(test_cases), result["time_ms"])
                return {"verdict": "RE", "detail": result["stderr"], "test": n, "test_results": test_results}

            # ── Runtime TLE (execution time_ms exceeds problem limit) ─────
            # DEFAULT_TIMEOUT_S is the hard wall; this catches soft per-problem limits.
            if result["time_ms"] > 2000:
                display_rows.append({"n": n, "status": "tle", "input": tc["input"],
                                      "expected": tc.get("expected_output",""), "got": "—", "time_ms": result["time_ms"]})
                test_results.append({"n": n, "passed": False, "verdict": "TLE",
                                      "time_ms": result["time_ms"], "actual_output": "", "stderr": "",
                                      "is_sample": is_sample})
                _skip_remaining(i+1, "TLE")
                _test_table(display_rows); _verdict_banner("TLE")
                _summary_row(submission_id, language, "TLE", passed, len(test_cases), result["time_ms"])
                return {"verdict": "TLE", "test": n, "time_ms": result["time_ms"], "test_results": test_results}

            expected = tc["expected_output"].strip()
            actual   = result["stdout"].strip()

            # ── Wrong answer ──────────────────────────────────────────────
            if actual != expected:
                display_rows.append({"n": n, "status": "fail", "input": tc["input"],
                                      "expected": expected, "got": actual, "time_ms": result["time_ms"]})
                test_results.append({"n": n, "passed": False, "verdict": "WA",
                                      "time_ms": result["time_ms"], "actual_output": actual,
                                      "stderr": "", "is_sample": is_sample})
                _skip_remaining(i+1, "WA")
                _test_table(display_rows); _verdict_banner("WA")
                _summary_row(submission_id, language, "WA", passed, len(test_cases), result["time_ms"])
                return {"verdict": "WA", "test": n, "expected": expected, "got": actual, "test_results": test_results}

            # ── Passed ────────────────────────────────────────────────────
            passed += 1
            display_rows.append({"n": n, "status": "pass", "input": tc["input"],
                                  "expected": expected, "got": actual, "time_ms": result["time_ms"]})
            test_results.append({"n": n, "passed": True, "verdict": "AC",
                                  "time_ms": result["time_ms"], "actual_output": actual,
                                  "stderr": "", "is_sample": is_sample})

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    _test_table(display_rows); _verdict_banner("AC")
    _summary_row(submission_id, language, "AC", passed, len(test_cases), result.get("time_ms", 0))
    return {"verdict": "AC", "time_ms": result.get("time_ms", 0), "test_results": test_results}


# ─────────────────────────────────────────────────────────────────────────────
# DB save
# ─────────────────────────────────────────────────────────────────────────────

def save_verdict(submission_id: str, result: dict):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute(
        """
        UPDATE submissions
        SET verdict = %s, status = 'done', time_ms = %s, test_results = %s
        WHERE id = %s
        """,
        (
            result["verdict"],
            result.get("time_ms", 0),
            json.dumps(result.get("test_results", [])),
            submission_id,
        ),
    )
    conn.commit()
    cur.close()
    conn.close()
    meta = VERDICT_META.get(result["verdict"], {"label": result["verdict"], "color": C.WHITE})
    _log("ok", f"Saved  {_c(submission_id, C.BOLD)}  →  {_c(meta['label'], C.BOLD, meta['color'])}")
    print(_divider())


# ─────────────────────────────────────────────────────────────────────────────
# /execute endpoint (used by /run in the API — sample cases only)
# ─────────────────────────────────────────────────────────────────────────────

run_api = Flask(__name__)

@run_api.post("/execute")
def execute():
    data = request.json
    try:
        language   = data["language"]
        code       = data["code"]
        test_cases = data.get("test_cases", [])

        results    = []
        all_passed = True
        total_time = 0

        for tc in test_cases:
            result = run_in_docker(language, code, tc["input"])
            actual   = result["stdout"].strip()
            expected = tc["expected_output"].strip()

            if result.get("ole"):
                verdict = "OLE"
                passed  = False
            elif result.get("tle") or result["time_ms"] > 2000:
                verdict = "TLE"
                passed  = False
            elif result["error"] == "runtime_error":
                verdict = "RE"
                passed  = False
            else:
                passed  = actual == expected
                verdict = "AC" if passed else "WA"

            if not passed:
                all_passed = False

            total_time += result["time_ms"]
            results.append({
                "passed":          passed,
                "verdict":         verdict,
                "time_ms":         result["time_ms"],
                "actual_output":   actual,
                "expected_output": expected,
                "input":           tc["input"],
                "stderr":          result.get("stderr", ""),
                "is_sample":       tc.get("is_sample", False),
            })

        first = results[0] if results else {}
        return jsonify({
            "stdout":    first.get("actual_output", ""),
            "stderr":    first.get("stderr", ""),
            "time_ms":   total_time,
            "exit_code": 0 if all_passed else 1,
            "results":   results,
            "verdict":   "AC" if all_passed else (results[0]["verdict"] if results else "SE"),
        })

    except Exception as e:
        return jsonify({"stdout": "", "stderr": str(e), "time_ms": 0, "exit_code": 1}), 500


# ─────────────────────────────────────────────────────────────────────────────
# RabbitMQ consumer
# ─────────────────────────────────────────────────────────────────────────────

def on_message(ch, method, properties, body):
    data = json.loads(body)
    result = judge(data["id"], data["language"], data["code"], data["test_cases"])
    save_verdict(data["id"], result)
    ch.basic_ack(delivery_tag=method.delivery_tag)


def start_worker():
    _header("Judge Worker  v2.0")

    with Spinner("Connecting to PostgreSQL…") as sp:
        setup_db()
    sp.stop(ok=True, final_msg="PostgreSQL ready.")

    # Verify seccomp profile on startup
    seccomp_path = os.path.abspath(SECCOMP_PROFILE_PATH)
    if os.path.exists(seccomp_path):
        _log("ok",   f"Seccomp profile  → {seccomp_path}")
    else:
        _log("warn", f"Seccomp profile missing at {seccomp_path}")
        _log("warn", "Containers will use Docker default seccomp — add sandbox/seccomp.json for full hardening")

    _log("info", "Connecting to RabbitMQ…")
    connection = pika.BlockingConnection(
        pika.ConnectionParameters(
            host=os.environ["RABBITMQ_HOST"],
            credentials=pika.PlainCredentials(
                os.environ["RABBITMQ_USER"],
                os.environ["RABBITMQ_PASSWORD"],
            ),
        )
    )

    threading.Thread(
        target=lambda: run_api.run(host="0.0.0.0", port=5050, debug=False),
        daemon=True,
    ).start()
    _log("ok", "Execution API running on port 5050")

    channel = connection.channel()
    channel.queue_declare(queue="submissions", durable=True)
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue="submissions", on_message_callback=on_message)

    _log("ok", f"Listening on queue  {_c('submissions', C.BRIGHT_CYAN)}  — {_c('ready.', C.DIM)}")
    print(_divider("━"))
    channel.start_consuming()


if __name__ == "__main__":
    start_worker()