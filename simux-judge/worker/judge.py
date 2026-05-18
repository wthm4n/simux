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


# ─────────────────────────────────────────────────────────────────────────────
# Terminal display helpers
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

    # Bright variants
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
    """level: 'info' | 'ok' | 'warn' | 'error' | 'dim'"""
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
    "AC": {
        "label": "Accepted",
        "desc":  "All test cases passed.",
        "icon":  "✔",
        "color": C.BRIGHT_GREEN,
        "bg":    C.BG_GREEN,
    },
    "WA": {
        "label": "Wrong Answer",
        "desc":  "Output did not match expected output.",
        "icon":  "✖",
        "color": C.BRIGHT_RED,
        "bg":    C.BG_RED,
    },
    "TLE": {
        "label": "Time Limit Exceeded",
        "desc":  "Program took longer than 2 000 ms to complete.",
        "icon":  "⧖",
        "color": C.BRIGHT_YELLOW,
        "bg":    C.BG_YELLOW,
    },
    "RE": {
        "label": "Runtime Error",
        "desc":  "Program crashed or exited with a non-zero code.",
        "icon":  "⚡",
        "color": C.BRIGHT_RED,
        "bg":    C.BG_RED,
    },
    "SE": {
        "label": "System Error",
        "desc":  "Internal judge error — please resubmit.",
        "icon":  "⚙",
        "color": C.BRIGHT_MAGENTA,
        "bg":    C.BG_MAGENTA,
    },
    "MLE": {
        "label": "Memory Limit Exceeded",
        "desc":  "Program exceeded the 256 MB memory limit.",
        "icon":  "◈",
        "color": C.BRIGHT_RED,
        "bg":    C.BG_RED,
    },
}


def _verdict_banner(verdict_code):
    meta = VERDICT_META.get(verdict_code, {
        "label": verdict_code,
        "desc":  "",
        "icon":  "?",
        "color": C.WHITE,
        "bg":    C.BG_WHITE,
    })
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
    """
    test_cases_results: list of dicts with keys:
      n, status ('pass'|'fail'|'tle'|'error'|'skip'),
      input, expected, got, time_ms, stderr (optional)
    """
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

    # Top border
    print(_c("┌" + "┬".join("─" * w for w in COL) + "┐", C.DIM))
    # Header
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
        status_label, status_color = STATUS_STYLE.get(
            t["status"], (t["status"], C.WHITE)
        )
        got_color      = C.BRIGHT_GREEN  if t["status"] == "pass" else C.BRIGHT_RED
        time_str       = f"{t['time_ms']} ms" if t["time_ms"] > 0 else "—"
        time_color     = (
            C.BRIGHT_YELLOW if t["time_ms"] > 1500
            else C.BRIGHT_RED if t["time_ms"] > 2000
            else C.DIM
        )

        row_colors = [
            C.WHITE,
            status_color,
            C.DIM,
            C.DIM,
            got_color if t["status"] in ("pass", "fail") else C.DIM,
            time_color,
        ]
        print(_row(
            [
                f"  #{t['n']}",
                f"  {status_label}",
                f"  {t.get('input', '')!r}",
                f"  {t.get('expected', '—')}",
                f"  {t.get('got', '—')}",
                f"  {time_str}",
            ],
            row_colors,
        ))

        # stderr inline below the failing row
        if t.get("stderr"):
            stderr_preview = t["stderr"].strip().replace("\n", " | ")[:120]
            print(
                _c("│", C.DIM)
                + _c(
                    f"  ↳ stderr: {stderr_preview}".ljust(sum(COL)),
                    C.BRIGHT_RED,
                )
                + _c("│", C.DIM)
            )

        if i < len(test_cases_results) - 1:
            print(_row_sep("├", "┼", "┤", "─"))

    # Bottom border
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
# DB Connection (unchanged logic)
# ─────────────────────────────────────────────────────────────────────────────

def get_db():
    return psycopg2.connect(
        host="host.docker.internal",
        database="judgedb",
        user="judge",
        password="judge123",
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
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.commit()
    cur.close()
    conn.close()
    _log("ok", "Database schema verified / ready.")


# ─────────────────────────────────────────────────────────────────────────────
# Language config (unchanged)
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
        "run_cmd": (
            "gcc /code/solution.c -o /code/solution -O2 -lm "
            "&& /code/solution < /code/input.txt"
        ),
    },
    "cpp": {
        "image":    "gcc:13",
        "filename": "solution.cpp",
        "run_cmd": (
            "g++ /code/solution.cpp -o /code/solution -O2 -std=c++17 "
            "&& /code/solution < /code/input.txt"
        ),
    },
    "java": {
        "image":    "eclipse-temurin:21-jdk-alpine",
        "filename": "Main.java",
        "run_cmd": (
            "javac /code/Main.java "
            "&& java -cp /code Main < /code/input.txt"
        ),
    },
    "javascript": {
        "image":    "node:20-slim",
        "filename": "solution.js",
        "run_cmd":  "node /code/solution.js < /code/input.txt",
    },
    "rust": {
        "image":    "rust:1.78-slim",
        "filename": "solution.rs",
        "run_cmd": (
            "rustc /code/solution.rs -o /code/solution --edition 2021 "
            "&& /code/solution < /code/input.txt"
        ),
    },
}

SLOW_COMPILE_LANGUAGES = {"rust", "java"}
COMPILE_TIMEOUT_S      = 30
DEFAULT_TIMEOUT_S      = 10


# ─────────────────────────────────────────────────────────────────────────────
# Docker runner (logic unchanged, print → _log)
# ─────────────────────────────────────────────────────────────────────────────

def run_in_docker(language, code, stdin_input=""):
    cfg = LANGUAGE_CONFIG.get(language)
    if cfg is None:
        _log("error", f"Unsupported language: '{language}'")
        return {
            "stdout": "",
            "stderr": f"unsupported language: '{language}'",
            "time_ms": 0,
            "error": "system_error",
        }

    client   = docker.from_env()
    image    = cfg["image"]
    filename = cfg["filename"]
    run_cmd  = cfg["run_cmd"]
    full_cmd = f'sh -c "{run_cmd}"'

    wall_limit = (
        COMPILE_TIMEOUT_S if language in SLOW_COMPILE_LANGUAGES else DEFAULT_TIMEOUT_S
    )

    tmp_dir = tempfile.mkdtemp()
    start   = time.time()

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

        spin_label = (
            f"Running {language} sandbox  (wall-clock limit: {wall_limit}s)…"
        )
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
            return {
                "stdout": "",
                "stderr": "",
                "time_ms": elapsed,
                "error": None,
                "tle": True,
            }

        if "exception" in result_holder:
            spinner.stop(ok=False, final_msg="Unexpected exception in container thread.")
            raise result_holder["exception"]

        if "error" in result_holder:
            e       = result_holder["error"]
            elapsed = int((time.time() - start) * 1000)
            stderr  = e.stderr.decode() if e.stderr else str(e)
            spinner.stop(ok=False, final_msg=f"Container exited with error ({elapsed} ms)")
            _log("error", f"stderr: {stderr[:200]}")
            return {
                "stdout": "",
                "stderr": stderr,
                "time_ms": elapsed,
                "error": "runtime_error",
            }

        elapsed = int((time.time() - start) * 1000)
        output  = result_holder.get("output", b"")
        stdout  = output.decode("utf-8").strip() if output else ""
        spinner.stop(ok=True, final_msg=f"Container finished in {elapsed} ms")
        _log("dim", f"stdout preview   → {repr(stdout[:80])}")
        return {
            "stdout": stdout,
            "stderr": "",
            "time_ms": elapsed,
            "error": None,
            "tle": False,
        }

    except Exception as e:
        _log("error", f"SYSTEM ERROR  {type(e).__name__}: {e}")
        return {"stdout": "", "stderr": str(e), "time_ms": 0, "error": "system_error"}

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────────────
# Judge (logic unchanged — collects per-test data for display)
# ─────────────────────────────────────────────────────────────────────────────

def judge(submission_id, language, code, test_cases):
    _section(f"Judging  {submission_id}  ({language})", "◈")

    result          = {}
    display_rows    = []   # collected for the table printed at the end
    passed          = 0

    for i, tc in enumerate(test_cases):
        n      = i + 1
        result = run_in_docker(language, code, tc["input"])

        # ── TLE (wall-clock) ──────────────────────────────────────────────
        if result.get("tle"):
            display_rows.append({
                "n": n, "status": "tle",
                "input": tc["input"], "expected": tc.get("expected_output", ""),
                "got": "—", "time_ms": result["time_ms"],
            })
            # mark remaining as skipped
            for j in range(i + 1, len(test_cases)):
                display_rows.append({
                    "n": j + 1, "status": "skip",
                    "input": test_cases[j]["input"],
                    "expected": test_cases[j].get("expected_output", ""),
                    "got": "—", "time_ms": 0,
                })
            _test_table(display_rows)
            _verdict_banner("TLE")
            _summary_row(submission_id, language, "TLE", passed, len(test_cases), result["time_ms"])
            return {"verdict": "TLE", "test": n, "time_ms": result["time_ms"]}

        # ── System error ──────────────────────────────────────────────────
        if result["error"] == "system_error":
            _log("error", f"System error on test #{n}: {result['stderr'][:200]}")
            _verdict_banner("SE")
            return {"verdict": "SE", "detail": result["stderr"]}

        # ── Runtime error ─────────────────────────────────────────────────
        if result["error"] == "runtime_error":
            display_rows.append({
                "n": n, "status": "error",
                "input": tc["input"], "expected": tc.get("expected_output", ""),
                "got": "—", "time_ms": result["time_ms"],
                "stderr": result["stderr"],
            })
            for j in range(i + 1, len(test_cases)):
                display_rows.append({
                    "n": j + 1, "status": "skip",
                    "input": test_cases[j]["input"],
                    "expected": test_cases[j].get("expected_output", ""),
                    "got": "—", "time_ms": 0,
                })
            _test_table(display_rows)
            _verdict_banner("RE")
            _summary_row(submission_id, language, "RE", passed, len(test_cases), result["time_ms"])
            return {"verdict": "RE", "detail": result["stderr"], "test": n}

        # ── Runtime TLE (2 000 ms hard cap) ───────────────────────────────
        if result["time_ms"] > 2000:
            display_rows.append({
                "n": n, "status": "tle",
                "input": tc["input"], "expected": tc.get("expected_output", ""),
                "got": "—", "time_ms": result["time_ms"],
            })
            for j in range(i + 1, len(test_cases)):
                display_rows.append({
                    "n": j + 1, "status": "skip",
                    "input": test_cases[j]["input"],
                    "expected": test_cases[j].get("expected_output", ""),
                    "got": "—", "time_ms": 0,
                })
            _test_table(display_rows)
            _verdict_banner("TLE")
            _summary_row(submission_id, language, "TLE", passed, len(test_cases), result["time_ms"])
            return {"verdict": "TLE", "test": n, "time_ms": result["time_ms"]}

        expected = tc["expected_output"].strip()
        actual   = result["stdout"].strip()

        # ── Wrong answer ──────────────────────────────────────────────────
        if actual != expected:
            display_rows.append({
                "n": n, "status": "fail",
                "input": tc["input"], "expected": expected,
                "got": actual, "time_ms": result["time_ms"],
            })
            for j in range(i + 1, len(test_cases)):
                display_rows.append({
                    "n": j + 1, "status": "skip",
                    "input": test_cases[j]["input"],
                    "expected": test_cases[j].get("expected_output", ""),
                    "got": "—", "time_ms": 0,
                })
            _test_table(display_rows)
            _verdict_banner("WA")
            _summary_row(submission_id, language, "WA", passed, len(test_cases), result["time_ms"])
            return {"verdict": "WA", "test": n, "expected": expected, "got": actual}

        # ── Passed ────────────────────────────────────────────────────────
        passed += 1
        display_rows.append({
            "n": n, "status": "pass",
            "input": tc["input"], "expected": expected,
            "got": actual, "time_ms": result["time_ms"],
        })

    _test_table(display_rows)
    _verdict_banner("AC")
    _summary_row(submission_id, language, "AC", passed, len(test_cases), result.get("time_ms", 0))
    return {"verdict": "AC", "time_ms": result.get("time_ms", 0)}


# ─────────────────────────────────────────────────────────────────────────────
# DB save (logic unchanged, print → _log)
# ─────────────────────────────────────────────────────────────────────────────

def save_verdict(submission_id, result):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute(
        """
        UPDATE submissions
        SET verdict = %s, status = 'done', time_ms = %s
        WHERE id = %s
        """,
        (result["verdict"], result.get("time_ms", 0), submission_id),
    )
    conn.commit()
    cur.close()
    conn.close()

    meta  = VERDICT_META.get(result["verdict"], {"label": result["verdict"], "color": C.WHITE})
    _log("ok", f"Saved  {_c(submission_id, C.BOLD)}  →  {_c(meta['label'], C.BOLD, meta['color'])}")
    print(_divider())


# ─────────────────────────────────────────────────────────────────────────────
# RabbitMQ consumer (logic unchanged, print → _log)
# ─────────────────────────────────────────────────────────────────────────────

def on_message(ch, method, properties, body):
    data = json.loads(body)

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
            host="host.docker.internal",
            credentials=pika.PlainCredentials("admin", "admin123"),
        )
    )
    channel = connection.channel()
    channel.queue_declare(queue="submissions", durable=True)
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue="submissions", on_message_callback=on_message)

    _log("ok", "RabbitMQ connected.")
    _log("ok",
         f"Listening on queue  {_c('submissions', C.BRIGHT_CYAN)}  "
         f"— {_c('ready for submissions.', C.DIM)}"
    )
    print(_divider("━"))

    channel.start_consuming()


if __name__ == "__main__":
    start_worker()