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
# Place seccomp.json in your sandbox/ folder and set this path.
# Example: /home/you/simux-judge/sandbox/seccomp.json
SECCOMP_PROFILE_PATH = os.environ.get(
    "SECCOMP_PROFILE_PATH",
    os.path.join(_dir, "..", "sandbox", "seccomp.json"),
)

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
    "python": {
        "image":    "python:3.11-slim",
        "filename": "solution.py",
        "run_cmd":  "python -u /code/solution.py < /code/input.txt",
    },
    "c": {
        "image":    "gcc:13",
        "filename": "solution.c",
        "run_cmd":  "gcc /code/solution.c -o /code/solution -O2 -lm && /code/solution < /code/input.txt",
    },
    "cpp": {
        "image":    "gcc:13",
        "filename": "solution.cpp",
        "run_cmd":  "g++ /code/solution.cpp -o /code/solution -O2 -std=c++17 && /code/solution < /code/input.txt",
    },
    "java": {
        "image":    "eclipse-temurin:21-jdk-alpine",
        "filename": "Main.java",
        "run_cmd":  "javac /code/Main.java && java -cp /code -Xmx200m Main < /code/input.txt",
    },
    "javascript": {
        "image":    "node:20-slim",
        "filename": "solution.js",
        "run_cmd":  "node --max-old-space-size=200 /code/solution.js < /code/input.txt",
    },
    "rust": {
        "image":    "rust:1.78-slim",
        "filename": "solution.rs",
        "run_cmd":  "rustc /code/solution.rs -o /code/solution --edition 2021 && /code/solution < /code/input.txt",
    },
}

SLOW_COMPILE_LANGUAGES = {"rust", "java"}
COMPILE_TIMEOUT_S      = 30
DEFAULT_TIMEOUT_S      = 10


# ─────────────────────────────────────────────────────────────────────────────
# Seccomp loader
# ─────────────────────────────────────────────────────────────────────────────

def _load_seccomp() -> dict | None:
    """
    Returns the seccomp security_opt list if the profile file exists,
    otherwise logs a warning and returns None (Docker default seccomp).
    """
    path = os.path.abspath(SECCOMP_PROFILE_PATH)
    if not os.path.exists(path):
        _log("warn", f"seccomp.json not found at {path} — using Docker default seccomp")
        return None
    try:
        with open(path) as f:
            profile = f.read()
        _log("dim", f"Seccomp profile loaded  → {path}")
        return [f"seccomp={profile}"]
    except Exception as e:
        _log("warn", f"Failed to load seccomp profile: {e} — using Docker default")
        return None


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
#   volumes rw only   — /code is the only writable path (tmpfs scratch)
#   user              — runs as unprivileged user nobody (65534)
#   cap_drop ALL      — all Linux capabilities dropped
#   security_opt      — no-new-privileges + custom seccomp profile
#   ulimits           — extra: 64 MB stack, 64 MB fsize, 16 MB core
#   stdout cap        — truncated at MAX_OUTPUT_BYTES (10 MB)
# ─────────────────────────────────────────────────────────────────────────────

def _build_security_opts() -> list[str]:
    opts = ["no-new-privileges"]
    seccomp = _load_seccomp()
    if seccomp:
        opts.extend(seccomp)
    return opts


def run_in_docker(language: str, code: str, stdin_input: str = "") -> dict:
    cfg = LANGUAGE_CONFIG.get(language)
    if cfg is None:
        _log("error", f"Unsupported language: '{language}'")
        return {"stdout": "", "stderr": f"unsupported language: '{language}'",
                "time_ms": 0, "error": "system_error"}

    client     = docker.from_env()
    image      = cfg["image"]
    filename   = cfg["filename"]
    run_cmd    = cfg["run_cmd"]
    full_cmd   = f'sh -c "{run_cmd}"'
    wall_limit = COMPILE_TIMEOUT_S if language in SLOW_COMPILE_LANGUAGES else DEFAULT_TIMEOUT_S
    tmp_dir    = tempfile.mkdtemp()
    start      = time.time()

    # Make the tmpdir world-readable so the nobody user inside the container
    # can read the code and input files.
    os.chmod(tmp_dir, 0o755)

    try:
        src_path   = os.path.join(tmp_dir, filename)
        input_path = os.path.join(tmp_dir, "input.txt")

        with open(src_path, "w") as f:
            f.write(code)
        with open(input_path, "w") as f:
            f.write(stdin_input)

        # World-readable so nobody (65534) can read them
        os.chmod(src_path,   0o644)
        os.chmod(input_path, 0o644)

        _log("dim", f"Sandbox mount  → {tmp_dir}")

        result_holder = {}

        def run_container():
            try:
                container = client.containers.run(
                    image=image,
                    command=full_cmd,

                    # ── Filesystem ─────────────────────────────────────────
                    volumes={tmp_dir: {"bind": "/code", "mode": "rw"}},
                    # Root fs is read-only; /code is the only writable path
                    read_only=True,
                    # Provide a writable /tmp via tmpfs (needed by some runtimes)
                    tmpfs={"/tmp": "size=64m,mode=1777"},

                    # ── Network ────────────────────────────────────────────
                    network_disabled=True,

                    # ── Resources ──────────────────────────────────────────
                    mem_limit="256m",
                    # Disable swap entirely (memswap = mem means no extra swap)
                    memswap_limit="256m",
                    cpu_quota=50000,          # 50% of one core (period=100000)
                    cpu_period=100000,
                    pids_limit=64,

                    # ── User ───────────────────────────────────────────────
                    # Run as nobody:nogroup inside the container
                    user="65534:65534",

                    # ── Capabilities ───────────────────────────────────────
                    cap_drop=["ALL"],

                    # ── Security ───────────────────────────────────────────
                    security_opt=_build_security_opts(),

                    # ── ulimits ────────────────────────────────────────────
                    ulimits=[
                        docker.types.Ulimit(name="stack",  soft=67108864,  hard=67108864),   # 64 MB stack
                        docker.types.Ulimit(name="fsize",  soft=67108864,  hard=67108864),   # 64 MB max file write
                        docker.types.Ulimit(name="core",   soft=0,         hard=0),           # no core dumps
                        docker.types.Ulimit(name="nofile", soft=64,        hard=64),          # 64 open file descriptors
                        docker.types.Ulimit(name="nproc",  soft=64,        hard=64),          # belt-and-suspenders pids
                    ],

                    # ── Cleanup ────────────────────────────────────────────
                    remove=True,
                    detach=True,
                )

                # Wait for completion; collect output with a hard byte cap
                exit_info = container.wait(timeout=wall_limit + 2)

                raw_stdout = container.logs(stdout=True,  stderr=False)
                raw_stderr = container.logs(stdout=False, stderr=True)

                # Output limit exceeded check
                ole = len(raw_stdout) > MAX_OUTPUT_BYTES
                stdout = raw_stdout[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace").strip()
                stderr = raw_stderr[:65536].decode("utf-8", errors="replace").strip()  # 64 KB stderr cap

                try:
                    container.remove(force=True)
                except Exception:
                    pass

                result_holder["result"] = {
                    "stdout":    stdout,
                    "stderr":    stderr,
                    "exit_code": exit_info.get("StatusCode", 1),
                    "ole":       ole,
                }

            except docker.errors.ContainerError as e:
                stderr = e.stderr.decode() if e.stderr else str(e)
                result_holder["runtime_error"] = stderr
            except Exception as e:
                result_holder["exception"] = e

        spinner = Spinner(f"Running {language} sandbox  (wall-clock: {wall_limit}s)…")
        spinner.start()

        thread = threading.Thread(target=run_container)
        thread.start()
        thread.join(timeout=wall_limit + 5)  # +5s grace for container.wait

        elapsed = int((time.time() - start) * 1000)

        # ── TLE: thread still alive after wall limit ──────────────────────
        if thread.is_alive():
            spinner.stop(ok=False, final_msg="Container timed out — killing…")
            _kill_orphan_containers(client, tmp_dir)
            return {"stdout": "", "stderr": "", "time_ms": elapsed,
                    "error": None, "tle": True}

        # ── Unexpected exception ──────────────────────────────────────────
        if "exception" in result_holder:
            spinner.stop(ok=False, final_msg="Unexpected exception.")
            raise result_holder["exception"]

        # ── Runtime error (ContainerError) ───────────────────────────────
        if "runtime_error" in result_holder:
            stderr = result_holder["runtime_error"]
            spinner.stop(ok=False, final_msg=f"Container exited with error ({elapsed} ms)")
            _log("error", f"stderr: {stderr[:200]}")
            return {"stdout": "", "stderr": stderr, "time_ms": elapsed,
                    "error": "runtime_error"}

        # ── Normal completion ─────────────────────────────────────────────
        r = result_holder.get("result", {})

        if r.get("ole"):
            spinner.stop(ok=False, final_msg=f"Output limit exceeded ({elapsed} ms)")
            return {"stdout": "", "stderr": "Output limit exceeded (>10 MB)", "time_ms": elapsed,
                    "error": None, "ole": True}

        # Non-zero exit code = runtime error
        if r.get("exit_code", 0) != 0 and not r.get("stdout"):
            spinner.stop(ok=False, final_msg=f"Non-zero exit code ({elapsed} ms)")
            return {"stdout": r.get("stdout",""), "stderr": r.get("stderr",""),
                    "time_ms": elapsed, "error": "runtime_error"}

        spinner.stop(ok=True, final_msg=f"Container finished in {elapsed} ms")
        _log("dim", f"stdout preview → {repr(r.get('stdout','')[:80])}")

        return {
            "stdout":  r.get("stdout", ""),
            "stderr":  r.get("stderr", ""),
            "time_ms": elapsed,
            "error":   None,
            "tle":     False,
        }

    except Exception as e:
        _log("error", f"SYSTEM ERROR  {type(e).__name__}: {e}")
        return {"stdout": "", "stderr": str(e), "time_ms": 0, "error": "system_error"}

    finally:
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

    result       = {}
    display_rows = []
    test_results = []
    passed       = 0

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

    for i, tc in enumerate(test_cases):
        n         = i + 1
        result    = run_in_docker(language, code, tc["input"])
        is_sample = tc.get("is_sample", False)

        # ── Output Limit Exceeded ─────────────────────────────────────────
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

        # ── TLE (wall-clock) ─────────────────────────────────────────────
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

        # ── System error ─────────────────────────────────────────────────
        if result["error"] == "system_error":
            _log("error", f"System error on test #{n}: {result['stderr'][:200]}")
            _verdict_banner("SE")
            test_results.append({"n": n, "passed": False, "verdict": "SE",
                                  "time_ms": 0, "actual_output": "", "stderr": result.get("stderr",""),
                                  "is_sample": is_sample})
            return {"verdict": "SE", "detail": result["stderr"], "test_results": test_results}

        # ── Runtime error ─────────────────────────────────────────────────
        if result["error"] == "runtime_error":
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

        # ── Runtime TLE (time_ms exceeds limit) ───────────────────────────
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

        # ── Wrong answer ──────────────────────────────────────────────────
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

        # ── Passed ────────────────────────────────────────────────────────
        passed += 1
        display_rows.append({"n": n, "status": "pass", "input": tc["input"],
                              "expected": expected, "got": actual, "time_ms": result["time_ms"]})
        test_results.append({"n": n, "passed": True, "verdict": "AC",
                              "time_ms": result["time_ms"], "actual_output": actual,
                              "stderr": "", "is_sample": is_sample})

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