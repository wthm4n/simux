import pika
import docker
import json
import uuid
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

# Load .env.judge (or fall back to .env) from the same directory as this file
_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_dir, '.env.judge'))
load_dotenv(os.path.join(_dir, '.env'))  # fallback


# ─────────────────────────────────────────────────────────────────────────────
# Terminal display helpers (unchanged from original)
# ─────────────────────────────────────────────────────────────────────────────

class C:
    """ANSI color/style codes."""
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    BLACK   = "\033[30m"
    RED     = "\033[31m"
    GREEN   = "\033[32m"
    YELLOW  = "\033[33m"
    BLUE    = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN    = "\033[36m"
    WHITE   = "\033[37m"
    BG_RED     = "\033[41m"
    BG_GREEN   = "\033[42m"
    BG_YELLOW  = "\033[43m"
    BG_BLUE    = "\033[44m"
    BG_MAGENTA = "\033[45m"
    BG_CYAN    = "\033[46m"
    BG_WHITE   = "\033[47m"
    BRIGHT_RED    = "\033[91m"
    BRIGHT_GREEN  = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE   = "\033[94m"
    BRIGHT_CYAN   = "\033[96m"
    BRIGHT_WHITE  = "\033[97m"
    BRIGHT_MAGENTA = "\033[95m"


def _c(text, *codes):
    return "".join(codes) + str(text) + C.RESET


def _divider(char="─", width=64, color=C.DIM):
    return _c(char * width, color)


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
    icons = {
        "info":  ("·", C.BRIGHT_BLUE),
        "ok":    ("✔", C.BRIGHT_GREEN),
        "warn":  ("⚠", C.BRIGHT_YELLOW),
        "error": ("✖", C.BRIGHT_RED),
        "dim":   ("·", C.DIM),
    }
    icon, color = icons.get(level, ("·", C.RESET))
    ts = _c(f"[{_timestamp()}]", C.DIM)
    print(f"  {ts} {_c(icon, color)}  {msg}")


def _timestamp():
    return time.strftime("%H:%M:%S")


# ── Spinner ───────────────────────────────────────────────────────────────────

class Spinner:
    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, label):
        self.label   = label
        self._stop   = threading.Event()
        self._thread = threading.Thread(target=self._spin, daemon=True)

    def _spin(self):
        for frame in itertools.cycle(self.FRAMES):
            if self._stop.is_set():
                break
            sys.stdout.write(f"\r  {_c(frame, C.BRIGHT_CYAN)}  {_c(self.label, C.DIM)}   ")
            sys.stdout.flush()
            time.sleep(0.08)
        sys.stdout.write("\r" + " " * (len(self.label) + 12) + "\r")
        sys.stdout.flush()

    def start(self):
        self._thread.start()
        return self

    def stop(self, ok=True, final_msg=None):
        self._stop.set()
        self._thread.join()
        icon  = _c("✔", C.BRIGHT_GREEN) if ok else _c("✖", C.BRIGHT_RED)
        label = final_msg or self.label
        print(f"  {icon}  {label}")

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, *_):
        self.stop(ok=(exc_type is None))


# ── Verdict display ───────────────────────────────────────────────────────────

VERDICT_META = {
    "AC": {"label": "Accepted",             "desc": "All test cases passed.",                   "icon": "✔", "color": C.BRIGHT_GREEN,   "bg": C.BG_GREEN},
    "WA": {"label": "Wrong Answer",         "desc": "Output did not match expected output.",    "icon": "✖", "color": C.BRIGHT_RED,     "bg": C.BG_RED},
    "TLE":{"label": "Time Limit Exceeded",  "desc": "Program took longer than 2 000 ms.",       "icon": "⧖", "color": C.BRIGHT_YELLOW,  "bg": C.BG_YELLOW},
    "RE": {"label": "Runtime Error",        "desc": "Program crashed or exited non-zero.",      "icon": "⚡", "color": C.BRIGHT_RED,     "bg": C.BG_RED},
    "SE": {"label": "System Error",         "desc": "Internal judge error — please resubmit.", "icon": "⚙", "color": C.BRIGHT_MAGENTA, "bg": C.BG_MAGENTA},
    "MLE":{"label": "Memory Limit Exceeded","desc": "Program exceeded the 256 MB memory limit.","icon": "◈", "color": C.BRIGHT_RED,     "bg": C.BG_RED},
}


def _verdict_banner(verdict_code):
    meta = VERDICT_META.get(verdict_code, {"label": verdict_code, "desc": "", "icon": "?", "color": C.WHITE, "bg": C.BG_WHITE})
    icon  = meta["icon"]
    label = meta["label"]
    desc  = meta["desc"]
    color = meta["color"]
    width = 64
    bar   = "━" * width
    inner = f"  {icon}  {label}"
    print(f"\n{_c(bar, color)}")
    print(_c(f"  {inner:<{width - 2}}", C.BOLD, color))
    if desc:
        print(_c(f"  {desc:<{width - 2}}", color))
    print(_c(bar, color))


def _test_table(test_cases_results):
    COL = [6, 10, 22, 16, 16, 9]
    HEADERS = ["Test", "Status", "Input", "Expected", "Got", "Time"]

    def _cell(text, width):
        s = str(text)
        if len(s) > width - 2:
            s = s[:width - 5] + "…"
        return s.ljust(width)

    def _row_sep(left="├", mid="┼", right="┤", bar="─"):
        return (
            _c(left, C.DIM)
            + _c(mid.join(bar * w for w in COL), C.DIM)
            + _c(right, C.DIM)
        )

    def _row(cells, colors=None):
        colors = colors or [C.RESET] * len(cells)
        parts  = []
        for i, (cell, w) in enumerate(zip(cells, COL)):
            parts.append(_c(_cell(cell, w), colors[i]))
        return _c("│", C.DIM) + _c("│", C.DIM).join(parts) + _c("│", C.DIM)

    print(_c("┌" + "┬".join("─" * w for w in COL) + "┐", C.DIM))
    print(_row(HEADERS, [C.BOLD] * len(HEADERS)))
    print(_row_sep())

    STATUS_STYLE = {
        "pass":  ("Passed",      C.BRIGHT_GREEN),
        "fail":  ("Wrong ans.",  C.BRIGHT_RED),
        "tle":   ("Time limit",  C.BRIGHT_YELLOW),
        "error": ("Runtime err", C.BRIGHT_RED),
        "skip":  ("Skipped",     C.DIM),
    }

    for i, t in enumerate(test_cases_results):
        status_label, status_color = STATUS_STYLE.get(t["status"], (t["status"], C.WHITE))
        got_color  = C.BRIGHT_GREEN if t["status"] == "pass" else C.BRIGHT_RED
        time_str   = f"{t['time_ms']} ms" if t["time_ms"] > 0 else "—"
        time_color = (
            C.BRIGHT_YELLOW if t["time_ms"] > 1500
            else C.BRIGHT_RED if t["time_ms"] > 2000
            else C.DIM
        )
        row_colors = [
            C.WHITE, status_color, C.DIM, C.DIM,
            got_color if t["status"] in ("pass", "fail") else C.DIM,
            time_color,
        ]
        print(_row([
            f"  #{t['n']}",
            f"  {status_label}",
            f"  {t.get('input', '')!r}",
            f"  {t.get('expected', '—')}",
            f"  {t.get('got', '—')}",
            f"  {time_str}",
        ], row_colors))

        if t.get("stderr"):
            stderr_preview = t["stderr"].strip().replace("\n", " | ")[:120]
            print(
                _c("│", C.DIM)
                + _c(f"  ↳ stderr: {stderr_preview}".ljust(sum(COL)), C.BRIGHT_RED)
                + _c("│", C.DIM)
            )

        if i < len(test_cases_results) - 1:
            print(_row_sep("├", "┼", "┤", "─"))

    print(_c("└" + "┴".join("─" * w for w in COL) + "┘", C.DIM))


def _summary_row(submission_id, language, verdict_code, passed, total, time_ms):
    meta  = VERDICT_META.get(verdict_code, {"color": C.WHITE, "label": verdict_code})
    color = meta["color"]
    label = meta["label"]
    print(
        f"\n  {_c('ID', C.DIM)}      {_c(submission_id, C.BOLD)}"
        f"\n  {_c('Language', C.DIM)} {_c(language, C.BRIGHT_CYAN)}"
        f"\n  {_c('Result', C.DIM)}   {_c(label, C.BOLD, color)}"
        f"\n  {_c('Tests', C.DIM)}    {_c(f'{passed}/{total} passed', C.BRIGHT_GREEN if passed == total else C.BRIGHT_RED)}"
        f"\n  {_c('Time', C.DIM)}     {_c(f'{time_ms} ms', C.DIM)}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# DB Connection — reads from environment
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
            test_results JSONB,
            problem_id INTEGER,
            user_id INTEGER,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    cur.execute("""
        ALTER TABLE submissions ADD COLUMN IF NOT EXISTS test_results JSONB
    """)
    conn.commit()
    cur.close()
    conn.close()
    _log("ok", "Database schema verified / ready.")


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
        "run_cmd":  "javac /code/Main.java && java -cp /code Main < /code/input.txt",
    },
    "javascript": {
        "image":    "node:20-slim",
        "filename": "solution.js",
        "run_cmd":  "node /code/solution.js < /code/input.txt",
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
# Docker runner
# Security flags verified:
#   network_disabled=True  — no outbound network
#   mem_limit="256m"       — 256 MB memory cap
#   cpu_quota=50000        — 50% of one CPU (100000 = 1 full core)
#   pids_limit=64          — prevents fork bombs
#   remove=True            — container cleaned up after each run
# ─────────────────────────────────────────────────────────────────────────────

def run_in_docker(language, code, stdin_input=""):
    cfg = LANGUAGE_CONFIG.get(language)
    if cfg is None:
        _log("error", f"Unsupported language: '{language}'")
        return {"stdout": "", "stderr": f"unsupported language: '{language}'", "time_ms": 0, "error": "system_error"}

    client   = docker.from_env()
    image    = cfg["image"]
    filename = cfg["filename"]
    run_cmd  = cfg["run_cmd"]
    full_cmd = f'sh -c "{run_cmd}"'

    wall_limit = COMPILE_TIMEOUT_S if language in SLOW_COMPILE_LANGUAGES else DEFAULT_TIMEOUT_S
    tmp_dir    = tempfile.mkdtemp()
    start      = time.time()

    try:
        with open(os.path.join(tmp_dir, filename), "w") as f:
            f.write(code)
        with open(os.path.join(tmp_dir, "input.txt"), "w") as f:
            f.write(stdin_input)

        _log("dim", f"Container mount  → {tmp_dir}")
        _log("dim", f"Files            → {os.listdir(tmp_dir)}")

        result_holder = {}

        def run_container():
            try:
                result_holder["output"] = client.containers.run(
                    image=image,
                    command=full_cmd,
                    volumes={tmp_dir: {"bind": "/code", "mode": "rw"}},
                    network_disabled=True,
                    mem_limit="256m",
                    cpu_quota=50000,
                    pids_limit=64,
                    remove=True,
                )
            except docker.errors.ContainerError as e:
                result_holder["error"] = e
            except Exception as e:
                result_holder["exception"] = e

        spin_label = f"Running {language} sandbox  (wall-clock limit: {wall_limit}s)…"
        spinner = Spinner(spin_label)
        spinner.start()

        thread = threading.Thread(target=run_container)
        thread.start()
        thread.join(timeout=wall_limit)

        if thread.is_alive():
            spinner.stop(ok=False, final_msg="Container timed out — killing…")
            try:
                for c in client.containers.list():
                    mounts = str(c.attrs.get("Mounts", ""))
                    if tmp_dir in mounts or os.path.basename(tmp_dir) in mounts:
                        c.kill()
            except Exception as kill_err:
                _log("warn", f"Kill error: {kill_err}")
            elapsed = int((time.time() - start) * 1000)
            return {"stdout": "", "stderr": "", "time_ms": elapsed, "error": None, "tle": True}

        if "exception" in result_holder:
            spinner.stop(ok=False, final_msg="Unexpected exception in container thread.")
            raise result_holder["exception"]

        if "error" in result_holder:
            e       = result_holder["error"]
            elapsed = int((time.time() - start) * 1000)
            stderr  = e.stderr.decode() if e.stderr else str(e)
            spinner.stop(ok=False, final_msg=f"Container exited with error ({elapsed} ms)")
            _log("error", f"stderr: {stderr[:200]}")
            return {"stdout": "", "stderr": stderr, "time_ms": elapsed, "error": "runtime_error"}

        elapsed = int((time.time() - start) * 1000)
        output  = result_holder.get("output", b"")
        stdout  = output.decode("utf-8").strip() if output else ""
        spinner.stop(ok=True, final_msg=f"Container finished in {elapsed} ms")
        _log("dim", f"stdout preview   → {repr(stdout[:80])}")
        return {"stdout": stdout, "stderr": "", "time_ms": elapsed, "error": None, "tle": False}

    except Exception as e:
        _log("error", f"SYSTEM ERROR  {type(e).__name__}: {e}")
        return {"stdout": "", "stderr": str(e), "time_ms": 0, "error": "system_error"}

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def execute_run(language, code, stdin_data=""):
    cfg = LANGUAGE_CONFIG.get(language)
    if cfg is None:
        return {"stdout": "", "stderr": f"unsupported language: {language}", "time_ms": 0, "exit_code": 1}

    client  = docker.from_env()
    tempdir = tempfile.mkdtemp()

    try:
        with open(os.path.join(tempdir, cfg["filename"]), "w", encoding="utf-8") as f:
            f.write(code)
        with open(os.path.join(tempdir, "input.txt"), "w", encoding="utf-8") as f:
            f.write(stdin_data)

        start = time.time()

        container = client.containers.run(
            image=cfg["image"],
            command=f'sh -c "{cfg["run_cmd"]}"',
            volumes={tempdir: {"bind": "/code", "mode": "rw"}},
            network_disabled=True,
            mem_limit="256m",
            cpu_quota=50000,
            pids_limit=64,
            detach=True,
            working_dir="/code",
        )

        result  = container.wait(timeout=5)
        elapsed = int((time.time() - start) * 1000)
        stdout  = container.logs(stdout=True,  stderr=False).decode(errors="ignore")
        stderr  = container.logs(stdout=False, stderr=True).decode(errors="ignore")
        container.remove(force=True)

        return {
            "stdout":    stdout.strip(),
            "stderr":    stderr.strip(),
            "time_ms":   elapsed,
            "exit_code": result.get("StatusCode", 1),
        }

    except Exception as e:
        return {"stdout": "", "stderr": str(e), "time_ms": 0, "exit_code": 1}

    finally:
        shutil.rmtree(tempdir, ignore_errors=True)


run_api = Flask(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Judge — full per-test breakdown
# ─────────────────────────────────────────────────────────────────────────────

def judge(submission_id, language, code, test_cases):
    _section(f"Judging  {submission_id}  ({language})", "◈")

    result       = {}
    display_rows = []
    passed       = 0
    test_results = []

    for i, tc in enumerate(test_cases):
        n         = i + 1
        result    = run_in_docker(language, code, tc["input"])
        is_sample = tc.get("is_sample", False)

        if result.get("tle"):
            display_rows.append({"n": n, "status": "tle", "input": tc["input"], "expected": tc.get("expected_output", ""), "got": "—", "time_ms": result["time_ms"]})
            test_results.append({"n": n, "passed": False, "verdict": "TLE", "time_ms": result["time_ms"], "actual_output": "", "stderr": "", "is_sample": is_sample})
            for j in range(i + 1, len(test_cases)):
                display_rows.append({"n": j + 1, "status": "skip", "input": test_cases[j]["input"], "expected": test_cases[j].get("expected_output", ""), "got": "—", "time_ms": 0})
                test_results.append({"n": j + 1, "passed": False, "verdict": "skip", "time_ms": 0, "actual_output": "", "stderr": "", "is_sample": test_cases[j].get("is_sample", False)})
            _test_table(display_rows)
            _verdict_banner("TLE")
            _summary_row(submission_id, language, "TLE", passed, len(test_cases), result["time_ms"])
            return {"verdict": "TLE", "test": n, "time_ms": result["time_ms"], "test_results": test_results}

        if result["error"] == "system_error":
            _log("error", f"System error on test #{n}: {result['stderr'][:200]}")
            _verdict_banner("SE")
            test_results.append({"n": n, "passed": False, "verdict": "SE", "time_ms": 0, "actual_output": "", "stderr": result.get("stderr", ""), "is_sample": is_sample})
            return {"verdict": "SE", "detail": result["stderr"], "test_results": test_results}

        if result["error"] == "runtime_error":
            display_rows.append({"n": n, "status": "error", "input": tc["input"], "expected": tc.get("expected_output", ""), "got": "—", "time_ms": result["time_ms"], "stderr": result["stderr"]})
            test_results.append({"n": n, "passed": False, "verdict": "RE", "time_ms": result["time_ms"], "actual_output": "", "stderr": result.get("stderr", ""), "is_sample": is_sample})
            for j in range(i + 1, len(test_cases)):
                display_rows.append({"n": j + 1, "status": "skip", "input": test_cases[j]["input"], "expected": test_cases[j].get("expected_output", ""), "got": "—", "time_ms": 0})
                test_results.append({"n": j + 1, "passed": False, "verdict": "skip", "time_ms": 0, "actual_output": "", "stderr": "", "is_sample": test_cases[j].get("is_sample", False)})
            _test_table(display_rows)
            _verdict_banner("RE")
            _summary_row(submission_id, language, "RE", passed, len(test_cases), result["time_ms"])
            return {"verdict": "RE", "detail": result["stderr"], "test": n, "test_results": test_results}

        if result["time_ms"] > 2000:
            display_rows.append({"n": n, "status": "tle", "input": tc["input"], "expected": tc.get("expected_output", ""), "got": "—", "time_ms": result["time_ms"]})
            test_results.append({"n": n, "passed": False, "verdict": "TLE", "time_ms": result["time_ms"], "actual_output": "", "stderr": "", "is_sample": is_sample})
            for j in range(i + 1, len(test_cases)):
                display_rows.append({"n": j + 1, "status": "skip", "input": test_cases[j]["input"], "expected": test_cases[j].get("expected_output", ""), "got": "—", "time_ms": 0})
                test_results.append({"n": j + 1, "passed": False, "verdict": "skip", "time_ms": 0, "actual_output": "", "stderr": "", "is_sample": test_cases[j].get("is_sample", False)})
            _test_table(display_rows)
            _verdict_banner("TLE")
            _summary_row(submission_id, language, "TLE", passed, len(test_cases), result["time_ms"])
            return {"verdict": "TLE", "test": n, "time_ms": result["time_ms"], "test_results": test_results}

        expected = tc["expected_output"].strip()
        actual   = result["stdout"].strip()

        if actual != expected:
            display_rows.append({"n": n, "status": "fail", "input": tc["input"], "expected": expected, "got": actual, "time_ms": result["time_ms"]})
            test_results.append({"n": n, "passed": False, "verdict": "WA", "time_ms": result["time_ms"], "actual_output": actual, "stderr": "", "is_sample": is_sample})
            for j in range(i + 1, len(test_cases)):
                display_rows.append({"n": j + 1, "status": "skip", "input": test_cases[j]["input"], "expected": test_cases[j].get("expected_output", ""), "got": "—", "time_ms": 0})
                test_results.append({"n": j + 1, "passed": False, "verdict": "skip", "time_ms": 0, "actual_output": "", "stderr": "", "is_sample": test_cases[j].get("is_sample", False)})
            _test_table(display_rows)
            _verdict_banner("WA")
            _summary_row(submission_id, language, "WA", passed, len(test_cases), result["time_ms"])
            return {"verdict": "WA", "test": n, "expected": expected, "got": actual, "test_results": test_results}

        passed += 1
        display_rows.append({"n": n, "status": "pass", "input": tc["input"], "expected": expected, "got": actual, "time_ms": result["time_ms"]})
        test_results.append({"n": n, "passed": True, "verdict": "AC", "time_ms": result["time_ms"], "actual_output": actual, "stderr": "", "is_sample": is_sample})

    _test_table(display_rows)
    _verdict_banner("AC")
    _summary_row(submission_id, language, "AC", passed, len(test_cases), result.get("time_ms", 0))
    return {"verdict": "AC", "time_ms": result.get("time_ms", 0), "test_results": test_results}


# ─────────────────────────────────────────────────────────────────────────────
# DB save
# ─────────────────────────────────────────────────────────────────────────────

def save_verdict(submission_id, result):
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
# /execute endpoint
# ─────────────────────────────────────────────────────────────────────────────

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
            passed   = actual == expected

            if not passed:
                all_passed = False

            total_time += result["time_ms"]

            verdict = (
                "RE"  if result["error"] == "runtime_error"
                else "TLE" if result.get("tle") or result["time_ms"] > 2000
                else "WA"  if not passed
                else "AC"
            )

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
            "verdict":   "AC" if all_passed else results[0]["verdict"] if results else "SE",
        })

    except Exception as e:
        return jsonify({"stdout": "", "stderr": str(e), "time_ms": 0, "exit_code": 1}), 500


# ─────────────────────────────────────────────────────────────────────────────
# RabbitMQ consumer
# ─────────────────────────────────────────────────────────────────────────────

def on_message(ch, method, properties, body):
    data          = json.loads(body)
    submission_id = data["id"]
    language      = data["language"]
    code          = data["code"]
    test_cases    = data["test_cases"]

    result = judge(submission_id, language, code, test_cases)
    save_verdict(submission_id, result)
    ch.basic_ack(delivery_tag=method.delivery_tag)


def start_worker():
    _header("Judge Worker  v1.0")

    with Spinner("Connecting to PostgreSQL…") as sp:
        setup_db()
    sp.stop(ok=True, final_msg="PostgreSQL ready.")

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

    _log("ok", "RabbitMQ connected.")
    _log("ok", f"Listening on queue  {_c('submissions', C.BRIGHT_CYAN)}  — {_c('ready for submissions.', C.DIM)}")
    print(_divider("━"))

    channel.start_consuming()


if __name__ == "__main__":
    start_worker()