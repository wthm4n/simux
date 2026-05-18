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


# --- DB Connection ---
def get_db():
    return psycopg2.connect(
        host="host.docker.internal",
        database="judgedb",
        user="judge",
        password="judge123",
    )


# --- Setup DB table ---
def setup_db():
    conn = get_db()
    cur = conn.cursor()
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
    print("DB ready")


# ---------------------------------------------------------------------------
# Language config
# ---------------------------------------------------------------------------
# Each entry defines everything needed to compile + run a submission.
#
#   image       – Docker image to pull (pre-pull these to avoid cold-start lag)
#   filename    – file written to the temp dir before running
#   run_cmd     – shell command executed INSIDE the container
#
# IMPORTANT — pre-pull all images on your host so the first submission isn't
# delayed by a multi-GB download:
#
#   docker pull python:3.11-slim
#   docker pull gcc:13
#   docker pull openjdk:21-slim
#   docker pull node:20-slim
#   docker pull rust:1.78-slim
# ---------------------------------------------------------------------------

LANGUAGE_CONFIG = {
    # ── Python ────────────────────────────────────────────────────────────
    "python": {
        "image": "python:3.11-slim",
        "filename": "solution.py",
        # -u disables output buffering so we always capture stdout fully
        "run_cmd": "python -u /code/solution.py < /code/input.txt",
    },
    # ── C ─────────────────────────────────────────────────────────────────
    # Uses the same gcc:13 image as C++; just different compiler flags.
    # -lm links the math library (needed for floor, sqrt, etc.)
    "c": {
        "image": "gcc:13",
        "filename": "solution.c",
        "run_cmd": (
            "gcc /code/solution.c -o /code/solution -O2 -lm "
            "&& /code/solution < /code/input.txt"
        ),
    },
    # ── C++ ───────────────────────────────────────────────────────────────
    # -O2 matches what most online judges use.
    # -std=c++17 covers nearly every modern CP problem.
    "cpp": {
        "image": "gcc:13",
        "filename": "solution.cpp",
        "run_cmd": (
            "g++ /code/solution.cpp -o /code/solution -O2 -std=c++17 "
            "&& /code/solution < /code/input.txt"
        ),
    },
    # ── Java ──────────────────────────────────────────────────────────────
    # CRITICAL: the public class in submitted code MUST be named "Main".
    # Enforce this on the frontend — tell users "your class must be Main".
    # -cp /code tells the JVM where to find Main.class after compilation.
    "java": {
        "image": "eclipse-temurin:21-jdk-alpine",
        "filename": "Main.java",
        "run_cmd": (
            "javac /code/Main.java " "&& java -cp /code Main < /code/input.txt"
        ),
    },
    # ── JavaScript (Node.js) ──────────────────────────────────────────────
    # readline / process.stdin work fine with stdin redirection.
    "javascript": {
        "image": "node:20-slim",
        "filename": "solution.js",
        "run_cmd": "node /code/solution.js < /code/input.txt",
    },
    # ── Rust ──────────────────────────────────────────────────────────────
    # Compilation is SLOW (~5-15 s on first build) — bump the TLE wall-clock
    # limit to at least 30 s, or pre-compile in a separate step.
    # --edition 2021 is the current default and covers all modern idioms.
    "rust": {
        "image": "rust:1.78-slim",
        "filename": "solution.rs",
        "run_cmd": (
            "rustc /code/solution.rs -o /code/solution --edition 2021 "
            "&& /code/solution < /code/input.txt"
        ),
    },
}

# Languages that have a long compile step — give them more wall-clock time
# before we declare TLE.  Runtime TLE limit stays at 2 000 ms.
SLOW_COMPILE_LANGUAGES = {"rust", "java"}
COMPILE_TIMEOUT_S = 30  # wall-clock timeout for slow-compile langs
DEFAULT_TIMEOUT_S = 10  # wall-clock timeout for everything else


# --- Run code in Docker ---
def run_in_docker(language, code, stdin_input=""):
    cfg = LANGUAGE_CONFIG.get(language)
    if cfg is None:
        return {
            "stdout": "",
            "stderr": f"unsupported language: '{language}'",
            "time_ms": 0,
            "error": "system_error",
        }

    client = docker.from_env()
    image = cfg["image"]
    filename = cfg["filename"]
    run_cmd = cfg["run_cmd"]
    full_cmd = f'sh -c "{run_cmd}"'

    # Pick the right wall-clock timeout
    wall_limit = (
        COMPILE_TIMEOUT_S if language in SLOW_COMPILE_LANGUAGES else DEFAULT_TIMEOUT_S
    )

    tmp_dir = tempfile.mkdtemp()
    start = time.time()

    try:
        with open(os.path.join(tmp_dir, filename), "w") as f:
            f.write(code)
        with open(os.path.join(tmp_dir, "input.txt"), "w") as f:
            f.write(stdin_input)

        print(f"[{language}] Mounting: {tmp_dir}")
        print(f"[{language}] Files: {os.listdir(tmp_dir)}")

        result_holder = {}

        def run_container():
            try:
                result_holder["output"] = client.containers.run(
                    image=image,
                    command=full_cmd,
                    volumes={tmp_dir: {"bind": "/code", "mode": "rw"}},
                    network_disabled=True,
                    mem_limit="256m",  # bumped: Java/Rust need more headroom
                    cpu_quota=50000,
                    pids_limit=64,  # bumped slightly for JVM threads
                    remove=True,
                )
            except docker.errors.ContainerError as e:
                result_holder["error"] = e
            except Exception as e:
                result_holder["exception"] = e

        thread = threading.Thread(target=run_container)
        thread.start()
        thread.join(timeout=wall_limit)

        if thread.is_alive():
            print(f"[{language}] TLE/compile-timeout — killing container...")
            try:
                for c in client.containers.list():
                    mounts = str(c.attrs.get("Mounts", ""))
                    if tmp_dir in mounts or os.path.basename(tmp_dir) in mounts:
                        c.kill()
            except Exception as kill_err:
                print(f"Kill error: {kill_err}")
            elapsed = int((time.time() - start) * 1000)
            return {
                "stdout": "",
                "stderr": "",
                "time_ms": elapsed,
                "error": None,
                "tle": True,
            }

        if "exception" in result_holder:
            raise result_holder["exception"]

        if "error" in result_holder:
            e = result_holder["error"]
            elapsed = int((time.time() - start) * 1000)
            stderr = e.stderr.decode() if e.stderr else str(e)
            print(f"[{language}] Container error: {stderr}")
            return {
                "stdout": "",
                "stderr": stderr,
                "time_ms": elapsed,
                "error": "runtime_error",
            }

        elapsed = int((time.time() - start) * 1000)
        output = result_holder.get("output", b"")
        stdout = output.decode("utf-8").strip() if output else ""
        print(f"[{language}] Output: '{stdout[:80]}' ({elapsed}ms)")
        return {
            "stdout": stdout,
            "stderr": "",
            "time_ms": elapsed,
            "error": None,
            "tle": False,
        }

    except Exception as e:
        print(f"[{language}] SYSTEM ERROR: {type(e).__name__}: {e}")
        return {"stdout": "", "stderr": str(e), "time_ms": 0, "error": "system_error"}

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# --- Judge against test cases ---
def judge(submission_id, language, code, test_cases):
    print(f"Judging {submission_id} ({language})")

    result = {}
    for i, tc in enumerate(test_cases):
        result = run_in_docker(language, code, tc["input"])

        if result.get("tle"):
            return {"verdict": "TLE", "test": i + 1, "time_ms": result["time_ms"]}

        if result["error"] == "system_error":
            return {"verdict": "SE", "detail": result["stderr"]}

        if result["error"] == "runtime_error":
            return {"verdict": "RE", "detail": result["stderr"], "test": i + 1}

        if result["time_ms"] > 2000:
            return {"verdict": "TLE", "test": i + 1, "time_ms": result["time_ms"]}

        expected = tc["expected_output"].strip()
        actual = result["stdout"].strip()

        if actual != expected:
            return {"verdict": "WA", "test": i + 1, "expected": expected, "got": actual}

    return {"verdict": "AC", "time_ms": result.get("time_ms", 0)}


# --- Save verdict to DB ---
def save_verdict(submission_id, result):
    conn = get_db()
    cur = conn.cursor()
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
    print(f"Saved: {submission_id} → {result['verdict']}")


# --- RabbitMQ consumer ---
def on_message(ch, method, properties, body):
    data = json.loads(body)

    submission_id = data["id"]
    language = data["language"]
    code = data["code"]
    test_cases = data["test_cases"]

    result = judge(submission_id, language, code, test_cases)
    save_verdict(submission_id, result)

    ch.basic_ack(delivery_tag=method.delivery_tag)


def start_worker():
    setup_db()

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

    print("Judge worker ready. Waiting for submissions...")
    channel.start_consuming()


if __name__ == "__main__":
    start_worker()
