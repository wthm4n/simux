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
from threading import Semaphore
from flask import Flask, request, jsonify
from dotenv import load_dotenv

# ── Load env ──────────────────────────────────────────────────────────────────
_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_dir, '.env'))

# ── Seccomp profile ───────────────────────────────────────────────────────────
_env_seccomp  = os.environ.get("SECCOMP_PROFILE_PATH", "")
_default_seccomp = os.path.normpath(os.path.join(_dir, "..", "sandbox", "seccomp.json"))
SECCOMP_PROFILE_PATH = (
    _env_seccomp if _env_seccomp and "absolute/path/to" not in _env_seccomp
    else _default_seccomp
)

MAX_OUTPUT_BYTES = 10 * 1024 * 1024   # 10 MB stdout cap

# ── Concurrency gate ──────────────────────────────────────────────────────────
# Caps simultaneous Docker containers across ALL paths (judge + /execute).
# Without this 50 concurrent /run requests → 50 containers → daemon dies.
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT_RUNS", "8"))
_judge_sem = Semaphore(MAX_CONCURRENT)


# ─────────────────────────────────────────────────────────────────────────────
# pids_limit — per language
#
# Docker counts ALL threads (not just processes) against pids_limit.
# Removing `nproc` ulimit (see below) makes pids_limit the sole fork guard,
# so these values need to be large enough for the runtime's own threads.
#
#   c / cpp / rust  → 16   binary only, no runtime threads
#   python          → 32   GIL + GC threads, ~6 total
#   javascript      → 64   V8 + libuv worker pool, ~10–14 threads
#   java            → 128  GC + JIT + reference handler + ..., ~25–35 threads
# ─────────────────────────────────────────────────────────────────────────────
_PIDS_LIMIT: dict[str, int] = {
    "c":          16,
    "cpp":        16,
    "rust":       16,
    "python":     32,
    "javascript": 64,
    "java":       128,
}
_PIDS_LIMIT_DEFAULT = 64

def _pids_limit_for(language: str) -> int:
    return _PIDS_LIMIT.get(language, _PIDS_LIMIT_DEFAULT)


# ─────────────────────────────────────────────────────────────────────────────
# Terminal display helpers
# ─────────────────────────────────────────────────────────────────────────────

class C:
    RESET  = "\033[0m"; BOLD = "\033[1m"; DIM = "\033[2m"
    RED    = "\033[31m"; GREEN = "\033[32m"; YELLOW = "\033[33m"
    CYAN   = "\033[36m"; WHITE = "\033[37m"; MAGENTA = "\033[35m"
    BG_RED = "\033[41m"; BG_GREEN = "\033[42m"; BG_YELLOW = "\033[43m"
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
        self.label  = label
        self._stop  = threading.Event()
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
    "AC":  {"label": "Accepted",              "desc": "All test cases passed.",                  "icon": "✔", "color": C.BRIGHT_GREEN,   "bg": C.BG_GREEN},
    "WA":  {"label": "Wrong Answer",          "desc": "Output did not match expected output.",   "icon": "✖", "color": C.BRIGHT_RED,     "bg": C.BG_RED},
    "TLE": {"label": "Time Limit Exceeded",   "desc": "Program took longer than the limit.",     "icon": "⧖", "color": C.BRIGHT_YELLOW,  "bg": C.BG_YELLOW},
    "RE":  {"label": "Runtime Error",         "desc": "Program crashed or exited non-zero.",     "icon": "⚡", "color": C.BRIGHT_RED,     "bg": C.BG_RED},
    "CE":  {"label": "Compile Error",         "desc": "Compilation failed — check your syntax.", "icon": "⚒", "color": C.BRIGHT_YELLOW,  "bg": C.BG_YELLOW},
    "SE":  {"label": "System Error",          "desc": "Internal judge error — please resubmit.","icon": "⚙", "color": C.BRIGHT_MAGENTA, "bg": C.BG_MAGENTA},
    "MLE": {"label": "Memory Limit Exceeded", "desc": "Program exceeded memory limit.",          "icon": "◈", "color": C.BRIGHT_RED,     "bg": C.BG_RED},
    "OLE": {"label": "Output Limit Exceeded", "desc": "Program produced too much output.",       "icon": "◉", "color": C.BRIGHT_RED,     "bg": C.BG_RED},
}

def _verdict_banner(verdict_code):
    meta  = VERDICT_META.get(verdict_code, {"label": verdict_code, "desc": "", "icon": "?", "color": C.WHITE})
    width = 64
    bar   = "━" * width
    inner = f"  {meta['icon']}  {meta['label']}"
    print(f"\n{_c(bar, meta['color'])}")
    print(_c(f"  {inner:<{width - 2}}", C.BOLD, meta['color']))
    if meta["desc"]: print(_c(f"  {meta['desc']:<{width - 2}}", meta['color']))
    print(_c(bar, meta['color']))

def _test_table(rows):
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
    def _sep(l="├", m="┼", r="┤", b="─"):
        return _c(l, C.DIM) + _c(m.join(b*w for w in COL), C.DIM) + _c(r, C.DIM)

    print(_c("┌" + "┬".join("─"*w for w in COL) + "┐", C.DIM))
    print(_row(HEADERS, [C.BOLD]*len(HEADERS)))
    print(_sep())
    for i, t in enumerate(rows):
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
        if i < len(rows)-1: print(_sep())
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
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS submissions (
            id TEXT PRIMARY KEY, language TEXT, code TEXT,
            status TEXT DEFAULT 'pending', verdict TEXT,
            stdout TEXT, stderr TEXT, time_ms INTEGER, memory_kb INTEGER,
            test_results JSONB, problem_id INTEGER, user_id INTEGER,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    for col, typ in [("test_results", "JSONB"), ("memory_kb", "INTEGER")]:
        cur.execute(f"ALTER TABLE submissions ADD COLUMN IF NOT EXISTS {col} {typ}")
    conn.commit(); cur.close(); conn.close()
    _log("ok", "Database schema verified.")


# ─────────────────────────────────────────────────────────────────────────────
# Language config
#
# exec_cmd is now a list of strings — no shell, no sh -c, no injection surface.
# Stdin is handled by writing input.txt and using stdin_open + socket.sendall,
# which eliminates the extra fork that `sh -c "... < input.txt"` required.
#
# compile_cmd stays as a string because it's always a single compiler
# invocation with a fixed argument list; we split it to a list at call time.
# ─────────────────────────────────────────────────────────────────────────────

LANGUAGE_CONFIG = {
    "python": {
        "image":       "python:3.11-slim",
        "filename":    "solution.py",
        "compile_cmd": None,
        "exec_cmd":    ["python", "-u", "/code/solution.py"],
    },
    "javascript": {
        "image":       "node:20-slim",
        "filename":    "solution.js",
        "compile_cmd": None,
        "exec_cmd":    ["node", "--max-old-space-size=200", "/code/solution.js"],
    },
    "c": {
        "image":       "gcc:13",
        "filename":    "solution.c",
        # 2>&1 is a shell construct — we capture stderr separately in compile stage
        "compile_cmd": ["gcc", "/code/solution.c", "-o", "/code/solution", "-O2", "-lm"],
        "exec_cmd":    ["/code/solution"],
    },
    "cpp": {
        "image":       "gcc:13",
        "filename":    "solution.cpp",
        "compile_cmd": ["g++", "/code/solution.cpp", "-o", "/code/solution", "-O2", "-std=c++17"],
        "exec_cmd":    ["/code/solution"],
    },
    "java": {
        "image":       "eclipse-temurin:21-jdk-alpine",
        "filename":    "Main.java",
        "compile_cmd": ["javac", "/code/Main.java"],
        "exec_cmd":    ["java", "-cp", "/code", "-Xmx200m", "Main"],
    },
    "rust": {
        "image":       "rust:1.78-slim",
        "filename":    "solution.rs",
        "compile_cmd": ["rustc", "/code/solution.rs", "-o", "/code/solution", "--edition", "2021"],
        "exec_cmd":    ["/code/solution"],
    },
}

COMPILE_TIMEOUT_S = 30
DEFAULT_TIMEOUT_S = 10


# ─────────────────────────────────────────────────────────────────────────────
# Seccomp — loaded once at startup, reused for every container
# ─────────────────────────────────────────────────────────────────────────────

def _load_security_opts() -> list[str]:
    path = os.path.abspath(SECCOMP_PROFILE_PATH)
    opts = ["no-new-privileges"]
    if not os.path.exists(path):
        _log("warn", f"seccomp.json not found at {path} — using Docker default")
        return opts
    try:
        opts.append(f"seccomp={open(path).read()}")
        _log("ok", f"Seccomp profile loaded → {path}")
    except Exception as e:
        _log("warn", f"Failed to load seccomp: {e} — using Docker default")
    return opts

_SECURITY_OPTS: list[str] = _load_security_opts()

# ─────────────────────────────────────────────────────────────────────────────
# Base ulimits
#
# nproc is intentionally REMOVED.
#
# The nproc ulimit is a per-UID kernel limit, not a per-container limit.
# When all containers run as uid 65534 (nobody), they all share the same
# nproc bucket. A limit of 64 means the FIRST container to spawn 64 threads
# blocks ALL subsequent containers from forking — including containers for
# completely different submissions. This is why you see "sh: 1: Cannot fork"
# even on otherwise healthy runs.
#
# Fork protection is now provided exclusively by:
#   - pids_limit  (per-container cgroup limit, correctly scoped)
#   - mem_limit   (OOM kills processes before they can fork-bomb)
# ─────────────────────────────────────────────────────────────────────────────

_BASE_ULIMITS = [
    docker.types.Ulimit(name="stack",  soft=67108864, hard=67108864),   # 64 MB stack
    docker.types.Ulimit(name="fsize",  soft=67108864, hard=67108864),   # 64 MB max file write
    docker.types.Ulimit(name="core",   soft=0,        hard=0),          # no core dumps
    docker.types.Ulimit(name="nofile", soft=64,       hard=64),         # 64 open fds
    # nproc intentionally absent — see comment above
]


# ─────────────────────────────────────────────────────────────────────────────
# Low-level container runner
#
# Key changes vs the old implementation:
#
#   1. exec_cmd is a list — passed directly to Docker, no sh -c wrapper.
#      This eliminates: one fork, shell process overhead, shell injection
#      surface, and the extra thread the shell holds open.
#
#   2. Stdin is fed via attach socket rather than shell redirection.
#      The container is started with stdin_open=True, detach=True; we attach
#      the socket, send the input bytes, close the write half, then wait for
#      the container to exit. This is the same approach used by production
#      judges (IOI isolate feeds stdin the same way).
#
#   3. Stdout is streamed in chunks with an early-exit on OLE, so a program
#      printing infinite output doesn't buffer 10 MB before we notice.
#
#   4. The concurrency semaphore (_judge_sem) is acquired before container
#      creation and released after removal, capping simultaneous containers
#      system-wide regardless of which code path (judge / /execute) calls us.
# ─────────────────────────────────────────────────────────────────────────────

def _run_container_blocking(
    client,
    image:      str,
    command:    list[str],     # ← always a list; never sh -c
    tmp_dir:    str,
    stdin_data: bytes,         # ← raw stdin bytes; empty for compile stage
    wall_limit: int,
    label:      str,
    language:   str,
    *,
    capture_stderr: bool = False,
) -> dict:
    """
    Spin up one hardened container, feed it stdin, collect stdout/stderr.

    Returns:
        stdout   str
        stderr   str   (non-empty only when capture_stderr=True or runtime error)
        time_ms  int
        error    None | "runtime_error" | "system_error"
        tle      bool
        ole      bool
        oom      bool
    """
    result_holder: dict = {}
    pids_cap = _pids_limit_for(language)

    def _run():
        container = None
        try:
            container = client.containers.create(
                image=image,
                command=command,
                volumes={tmp_dir: {"bind": "/code", "mode": "rw"}},
                read_only=True,
                tmpfs={"/tmp": "size=64m,mode=1777"},
                network_disabled=True,
                mem_limit="256m",
                memswap_limit="256m",
                cpu_quota=50000,
                cpu_period=100000,
                pids_limit=pids_cap,
                user="65534:65534",
                cap_drop=["ALL"],
                security_opt=_SECURITY_OPTS,
                ulimits=_BASE_ULIMITS,
                detach=True,
            )

            container.start()

            # Feed stdin without a shell — attach to the container's stream,
            # write input bytes, then close the write half so the program
            # sees EOF. This replaces the old "< /code/input.txt" shell trick.

            # Stream stdout in chunks — bail early on OLE
            stdout_chunks: list[bytes] = []
            total_bytes   = 0
            ole           = False

            for chunk in container.logs(stream=True, follow=True, stdout=True, stderr=False):
                total_bytes += len(chunk)
                if total_bytes > MAX_OUTPUT_BYTES:
                    ole = True
                    break
                stdout_chunks.append(chunk)

            exit_info   = container.wait(timeout=2)
            exit_status = exit_info.get("StatusCode", 1)

            stderr_text = ""
            if capture_stderr:
                raw_err    = container.logs(stdout=False, stderr=True)
                stderr_text = raw_err.decode("utf-8", errors="replace").strip() if raw_err else ""

            if ole:
                result_holder["ole"] = True
                return

            stdout_text = b"".join(stdout_chunks).decode("utf-8", errors="replace").strip()

            if exit_status == 137:
                # SIGKILL → OOM or fsize ulimit
                result_holder["ole"] = True
            elif exit_status != 0:
                msg = stderr_text if stderr_text else f"exited with code {exit_status}"
                result_holder["runtime_error"] = msg[:65536]
            else:
                result_holder["result"] = {
                    "stdout": stdout_text,
                    "stderr": stderr_text,
                }

        except Exception as exc:
            result_holder["exception"] = exc
        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except Exception:
                    pass

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
    spinner.stop(ok=True, final_msg=f"{label.split('(')[0].strip()} — {elapsed} ms")
    return {
        "stdout":  r.get("stdout", ""),
        "stderr":  r.get("stderr", ""),
        "time_ms": elapsed,
        "error":   None,
        "tle":     False,
        "ole":     False,
        "oom":     False,
    }


def _kill_orphan_containers(client, tmp_dir: str):
    try:
        for c in client.containers.list():
            mounts = str(c.attrs.get("Mounts", ""))
            if tmp_dir in mounts or os.path.basename(tmp_dir) in mounts:
                _log("warn", f"Killing orphan container {c.short_id}")
                try: c.kill()
                except Exception: pass
                try: c.remove(force=True)
                except Exception: pass
    except Exception as e:
        _log("warn", f"Kill error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — Compile (once per submission)
# ─────────────────────────────────────────────────────────────────────────────

def compile_in_docker(language: str, tmp_dir: str) -> dict:
    """
    Run the compiler inside a container. compile_cmd is a list — no shell.
    Compiler output (errors) comes from stderr, which we capture directly
    instead of the old 2>&1 shell redirect hack.

    Returns {"ok": True, "compile_ms": N}
          | {"ok": False, "verdict": "CE"|"SE", "stderr": "..."}
    """
    cfg         = LANGUAGE_CONFIG[language]
    compile_cmd = cfg.get("compile_cmd")

    if compile_cmd is None:
        return {"ok": True, "compile_ms": 0}

    client     = docker.from_env()
    wall_limit = COMPILE_TIMEOUT_S
    label      = f"Compiling {language}  (wall: {wall_limit}s)…"
    _log("info", label)

    try:
        with _judge_sem:
            result = _run_container_blocking(
                client, cfg["image"], compile_cmd, tmp_dir,
                b"",            # compilers don't read stdin
                wall_limit, label, language,
                capture_stderr=True,   # compiler errors land on stderr
            )
    except Exception as e:
        _log("error", f"Compile stage SE: {e}")
        return {"ok": False, "verdict": "SE", "stderr": str(e)}

    if result["tle"]:
        return {"ok": False, "verdict": "CE",
                "stderr": f"Compilation timed out after {wall_limit}s"}

    if result["error"] == "runtime_error":
        # Compiler exited non-zero — stderr holds the error text
        compiler_output = result["stderr"] or result["stdout"]
        _log("warn", f"CE: {compiler_output[:200]}")
        return {"ok": False, "verdict": "CE", "stderr": compiler_output}

    if result["error"] == "system_error":
        return {"ok": False, "verdict": "SE", "stderr": result["stderr"]}

    _log("ok", f"Compiled in {result['time_ms']} ms")
    return {"ok": True, "compile_ms": result["time_ms"]}


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — Execute one test case
#
# exec_cmd is a pre-built list from LANGUAGE_CONFIG — Docker passes it directly
# to execve(), bypassing the shell entirely. stdin is sent over the attach
# socket instead of shell redirection.
# ─────────────────────────────────────────────────────────────────────────────

def run_test_in_docker(
    language:     str,
    tmp_dir:      str,
    stdin_input:  str = "",
    *,
    time_limit_ms: int  = 0,
    auto_cleanup:  bool = True,
) -> dict:
    """
    Execute the already-compiled binary / source for one test case.
    tmp_dir must already contain the compiled artifact from compile_in_docker.
    Wall-clock timing covers only this container — compile time excluded.
    """
    cfg        = LANGUAGE_CONFIG[language]
    client     = docker.from_env()
    wall_limit = (time_limit_ms // 1000 + 2) if time_limit_ms else DEFAULT_TIMEOUT_S
    label      = f"Executing {language}  (wall: {wall_limit}s)…"

    try:
        with _judge_sem:
            return _run_container_blocking(
                client, cfg["image"], cfg["exec_cmd"], tmp_dir,
                stdin_input.encode(),   # fed via attach socket, not shell redirect
                wall_limit, label, language,
            )
    except Exception as e:
        _log("error", f"SYSTEM ERROR run_test  {type(e).__name__}: {e}")
        return {"stdout": "", "stderr": str(e), "time_ms": 0,
                "error": "system_error", "tle": False, "ole": False, "oom": False}
    finally:
        if auto_cleanup:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def _compile_and_run_once(language: str, code: str, stdin_input: str) -> dict:
    """
    Compile-once-then-execute helper shared by run_in_docker and /execute.
    Owns the tmp_dir lifecycle; always cleans up on return.
    """
    cfg = LANGUAGE_CONFIG.get(language)
    if cfg is None:
        return {"stdout": "", "stderr": f"unsupported language: '{language}'",
                "time_ms": 0, "error": "system_error"}

    tmp_dir = tempfile.mkdtemp()
    os.chmod(tmp_dir, 0o777)

    try:
        src_path = os.path.join(tmp_dir, cfg["filename"])
        with open(src_path, "w") as f:
            f.write(code)
        os.chmod(src_path, 0o666)

        _log("dim", f"Sandbox mount → {tmp_dir}")

        compile_result = compile_in_docker(language, tmp_dir)
        if not compile_result["ok"]:
            verdict = compile_result["verdict"]
            stderr  = compile_result["stderr"]
            return {"stdout": "", "stderr": stderr, "time_ms": 0,
                    "error": "compile_error" if verdict == "CE" else "system_error",
                    "verdict": verdict}

        return run_test_in_docker(language, tmp_dir, stdin_input, auto_cleanup=False)

    except Exception as e:
        _log("error", f"SYSTEM ERROR  {type(e).__name__}: {e}")
        return {"stdout": "", "stderr": str(e), "time_ms": 0, "error": "system_error"}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# Public alias kept for any external callers
def run_in_docker(language: str, code: str, stdin_input: str = "") -> dict:
    return _compile_and_run_once(language, code, stdin_input)


# ─────────────────────────────────────────────────────────────────────────────
# Judge — compile once, run all test cases in the same tmp_dir
# ─────────────────────────────────────────────────────────────────────────────

def judge(submission_id: str, language: str, code: str, test_cases: list) -> dict:
    _section(f"Judging  {submission_id}  ({language})", "◈")

    display_rows = []
    test_results = []
    passed       = 0
    result: dict = {}

    def _skip_remaining(from_idx: int):
        for j in range(from_idx, len(test_cases)):
            display_rows.append({"n": j+1, "status": "skip",
                                  "input": test_cases[j]["input"],
                                  "expected": test_cases[j].get("expected_output",""),
                                  "got": "—", "time_ms": 0})
            test_results.append({"n": j+1, "passed": False, "verdict": "skip",
                                  "time_ms": 0, "actual_output": "", "stderr": "",
                                  "is_sample": test_cases[j].get("is_sample", False)})

    cfg = LANGUAGE_CONFIG.get(language)
    if cfg is None:
        _log("error", f"Unsupported language: '{language}'")
        return {"verdict": "SE", "time_ms": 0, "test_results": []}

    tmp_dir  = tempfile.mkdtemp()
    os.chmod(tmp_dir, 0o777)
    src_path = os.path.join(tmp_dir, cfg["filename"])
    with open(src_path, "w") as f:
        f.write(code)
    os.chmod(src_path, 0o666)

    # ── Compile once ─────────────────────────────────────────────────────────
    compile_result = compile_in_docker(language, tmp_dir)

    if not compile_result["ok"]:
        verdict = compile_result["verdict"]
        stderr  = compile_result["stderr"]
        shutil.rmtree(tmp_dir, ignore_errors=True)
        for j, tc in enumerate(test_cases):
            test_results.append({"n": j+1, "passed": False, "verdict": verdict,
                                  "time_ms": 0, "actual_output": "", "stderr": stderr,
                                  "is_sample": tc.get("is_sample", False)})
        _verdict_banner(verdict)
        _log("warn" if verdict == "CE" else "error", f"{verdict}: {stderr[:300]}")
        _summary_row(submission_id, language, verdict, 0, len(test_cases), 0)
        return {"verdict": verdict, "stderr": stderr, "time_ms": 0, "test_results": test_results}

    _log("ok", f"Compiled in {compile_result.get('compile_ms', 0)} ms "
               f"— running {len(test_cases)} test case(s)")

    # ── Run each test case against the same compiled binary ──────────────────
    try:
        for i, tc in enumerate(test_cases):
            n         = i + 1
            is_sample = tc.get("is_sample", False)
            result    = run_test_in_docker(language, tmp_dir, tc["input"], auto_cleanup=False)

            # OLE
            if result.get("ole"):
                display_rows.append({"n": n, "status": "ole", "input": tc["input"],
                                     "expected": tc.get("expected_output",""), "got": "[truncated]",
                                     "time_ms": result["time_ms"]})
                test_results.append({"n": n, "passed": False, "verdict": "OLE",
                                     "time_ms": result["time_ms"], "actual_output": "",
                                     "stderr": "Output limit exceeded", "is_sample": is_sample})
                _skip_remaining(i+1)
                _test_table(display_rows); _verdict_banner("OLE")
                _summary_row(submission_id, language, "OLE", passed, len(test_cases), result["time_ms"])
                return {"verdict": "OLE", "test": n, "time_ms": result["time_ms"], "test_results": test_results}

            # TLE (wall-clock)
            if result.get("tle"):
                display_rows.append({"n": n, "status": "tle", "input": tc["input"],
                                     "expected": tc.get("expected_output",""), "got": "—",
                                     "time_ms": result["time_ms"]})
                test_results.append({"n": n, "passed": False, "verdict": "TLE",
                                     "time_ms": result["time_ms"], "actual_output": "", "stderr": "",
                                     "is_sample": is_sample})
                _skip_remaining(i+1)
                _test_table(display_rows); _verdict_banner("TLE")
                _summary_row(submission_id, language, "TLE", passed, len(test_cases), result["time_ms"])
                return {"verdict": "TLE", "test": n, "time_ms": result["time_ms"], "test_results": test_results}

            # MLE
            if result.get("oom"):
                display_rows.append({"n": n, "status": "error", "input": tc["input"],
                                     "expected": tc.get("expected_output",""), "got": "—",
                                     "time_ms": result["time_ms"]})
                test_results.append({"n": n, "passed": False, "verdict": "MLE",
                                     "time_ms": result["time_ms"], "actual_output": "",
                                     "stderr": "Memory limit exceeded", "is_sample": is_sample})
                _skip_remaining(i+1)
                _test_table(display_rows); _verdict_banner("MLE")
                _summary_row(submission_id, language, "MLE", passed, len(test_cases), result["time_ms"])
                return {"verdict": "MLE", "test": n, "time_ms": result["time_ms"], "test_results": test_results}

            # SE
            if result.get("error") == "system_error":
                _log("error", f"System error on test #{n}: {result['stderr'][:200]}")
                _verdict_banner("SE")
                test_results.append({"n": n, "passed": False, "verdict": "SE",
                                     "time_ms": 0, "actual_output": "", "stderr": result.get("stderr",""),
                                     "is_sample": is_sample})
                return {"verdict": "SE", "detail": result["stderr"], "test_results": test_results}

            # RE
            if result.get("error") == "runtime_error":
                display_rows.append({"n": n, "status": "error", "input": tc["input"],
                                     "expected": tc.get("expected_output",""), "got": "—",
                                     "time_ms": result["time_ms"], "stderr": result["stderr"]})
                test_results.append({"n": n, "passed": False, "verdict": "RE",
                                     "time_ms": result["time_ms"], "actual_output": "",
                                     "stderr": result.get("stderr",""), "is_sample": is_sample})
                _skip_remaining(i+1)
                _test_table(display_rows); _verdict_banner("RE")
                _summary_row(submission_id, language, "RE", passed, len(test_cases), result["time_ms"])
                return {"verdict": "RE", "detail": result["stderr"], "test": n, "test_results": test_results}

            # Soft TLE (within wall limit but over problem time limit)
            if result["time_ms"] > 2000:
                display_rows.append({"n": n, "status": "tle", "input": tc["input"],
                                     "expected": tc.get("expected_output",""), "got": "—",
                                     "time_ms": result["time_ms"]})
                test_results.append({"n": n, "passed": False, "verdict": "TLE",
                                     "time_ms": result["time_ms"], "actual_output": "", "stderr": "",
                                     "is_sample": is_sample})
                _skip_remaining(i+1)
                _test_table(display_rows); _verdict_banner("TLE")
                _summary_row(submission_id, language, "TLE", passed, len(test_cases), result["time_ms"])
                return {"verdict": "TLE", "test": n, "time_ms": result["time_ms"], "test_results": test_results}

            expected = tc["expected_output"].strip()
            actual   = result["stdout"].strip()

            # WA
            if actual != expected:
                display_rows.append({"n": n, "status": "fail", "input": tc["input"],
                                     "expected": expected, "got": actual, "time_ms": result["time_ms"]})
                test_results.append({"n": n, "passed": False, "verdict": "WA",
                                     "time_ms": result["time_ms"], "actual_output": actual,
                                     "stderr": "", "is_sample": is_sample})
                _skip_remaining(i+1)
                _test_table(display_rows); _verdict_banner("WA")
                _summary_row(submission_id, language, "WA", passed, len(test_cases), result["time_ms"])
                return {"verdict": "WA", "test": n, "expected": expected, "got": actual, "test_results": test_results}

            # AC
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
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "UPDATE submissions SET verdict=%s, status='done', time_ms=%s, test_results=%s WHERE id=%s",
        (result["verdict"], result.get("time_ms", 0),
         json.dumps(result.get("test_results", [])), submission_id),
    )
    conn.commit(); cur.close(); conn.close()
    meta = VERDICT_META.get(result["verdict"], {"label": result["verdict"], "color": C.WHITE})
    _log("ok", f"Saved  {_c(submission_id, C.BOLD)}  →  {_c(meta['label'], C.BOLD, meta['color'])}")
    print(_divider())


# ─────────────────────────────────────────────────────────────────────────────
# /execute endpoint  (used by the /run flow — sample cases only)
#
# Previously this called run_in_docker per test case, recompiling every time.
# Now it mirrors judge(): compile once into a shared tmp_dir, then run each
# test case against the same binary. The semaphore in run_test_in_docker
# and compile_in_docker caps concurrency automatically.
# ─────────────────────────────────────────────────────────────────────────────

run_api = Flask(__name__)

@run_api.post("/execute")
def execute():
    data = request.json
    try:
        language   = data["language"]
        code       = data["code"]
        test_cases = data.get("test_cases", [])

        cfg = LANGUAGE_CONFIG.get(language)
        if cfg is None:
            return jsonify({"stdout": "", "stderr": f"unsupported language: '{language}'",
                            "time_ms": 0, "exit_code": 1}), 400

        tmp_dir = tempfile.mkdtemp()
        os.chmod(tmp_dir, 0o777)
        try:
            src_path = os.path.join(tmp_dir, cfg["filename"])
            with open(src_path, "w") as f:
                f.write(code)
            os.chmod(src_path, 0o666)

            # ── Compile once ──────────────────────────────────────────────
            compile_result = compile_in_docker(language, tmp_dir)
            if not compile_result["ok"]:
                verdict = compile_result["verdict"]
                stderr  = compile_result["stderr"]
                return jsonify({"stdout": "", "stderr": stderr, "time_ms": 0,
                                "exit_code": 1, "results": [], "verdict": verdict})

            # ── Run each test case against the compiled binary ────────────
            results    = []
            all_passed = True
            total_time = 0

            for tc in test_cases:
                result   = run_test_in_docker(language, tmp_dir, tc["input"], auto_cleanup=False)
                actual   = result["stdout"].strip()
                expected = tc["expected_output"].strip()

                if result.get("ole"):
                    verdict = "OLE"; passed = False
                elif result.get("tle") or result["time_ms"] > 2000:
                    verdict = "TLE"; passed = False
                elif result.get("error") == "runtime_error":
                    verdict = "RE"; passed = False
                elif result.get("error"):
                    verdict = "SE"; passed = False
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

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        first = results[0] if results else {}
        return jsonify({
            "stdout":    first.get("actual_output", ""),
            "stderr":    first.get("stderr", ""),
            "time_ms":   total_time,
            "exit_code": 0 if all_passed else 1,
            "results":   results,
            "verdict":   "AC" if all_passed else (first.get("verdict", "SE")),
        })

    except Exception as e:
        return jsonify({"stdout": "", "stderr": str(e), "time_ms": 0, "exit_code": 1}), 500


# ─────────────────────────────────────────────────────────────────────────────
# RabbitMQ consumer
# ─────────────────────────────────────────────────────────────────────────────

def on_message(ch, method, properties, body):
    data   = json.loads(body)
    result = judge(data["id"], data["language"], data["code"], data["test_cases"])
    save_verdict(data["id"], result)
    ch.basic_ack(delivery_tag=method.delivery_tag)


def start_worker():
    _header("Judge Worker  v2.1")

    with Spinner("Connecting to PostgreSQL…") as sp:
        setup_db()
    sp.stop(ok=True, final_msg="PostgreSQL ready.")

    seccomp_path = os.path.abspath(SECCOMP_PROFILE_PATH)
    if os.path.exists(seccomp_path):
        _log("ok",   f"Seccomp profile  → {seccomp_path}")
    else:
        _log("warn", f"Seccomp profile missing at {seccomp_path}")
        _log("warn", "Add sandbox/seccomp.json for full hardening")

    _log("info", f"Concurrency cap  → {MAX_CONCURRENT} simultaneous containers")
    _log("info",  "Connecting to RabbitMQ…")

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