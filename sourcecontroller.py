import subprocess
import time
import threading
import itertools
import hashlib
import os
import sys
from datetime import datetime
from collections import deque

# ═════════════════════════════════════════════════════════════
# COLORS
# ═════════════════════════════════════════════════════════════

class C:
    RESET = "\033[0m"

    BOLD = "\033[1m"
    DIM = "\033[2m"

    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"


def c(text, *codes):
    return "".join(codes) + str(text) + C.RESET


# ═════════════════════════════════════════════════════════════
# CONFIG
# ═════════════════════════════════════════════════════════════

PUSH_INTERVAL = 5

IGNORE = {
    ".git",
    "node_modules",
    "__pycache__",
    ".next",
    "dist",
    "build",
    "venv"
}

last_hashes = {}
recent_logs = deque(maxlen=8)
recent_commits = deque(maxlen=6)
changed_files_live = deque(maxlen=10)

pending_push = False
last_push = time.time()
push_count = 0
commit_count = 0

spinner_index = 0

SPINNER = [
    "⠋","⠙","⠹","⠸","⠼",
    "⠴","⠦","⠧","⠇","⠏"
]

# ═════════════════════════════════════════════════════════════
# TERMINAL
# ═════════════════════════════════════════════════════════════

def clear():
    os.system("cls" if os.name == "nt" else "clear")


def ts():
    return datetime.now().strftime("%H:%M:%S")


def log(msg, color=C.BRIGHT_WHITE):
    recent_logs.appendleft(
        f"{c(ts(), C.DIM)} {c(msg, color)}"
    )


# ═════════════════════════════════════════════════════════════
# GIT
# ═════════════════════════════════════════════════════════════

def run(cmd):
    return subprocess.check_output(
        cmd,
        shell=True,
        text=True
    ).strip()


def silent(cmd):
    return subprocess.run(
        cmd,
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )


def get_branch():
    try:
        return run("git branch --show-current")
    except:
        return "unknown"


def get_changed_files():
    try:
        output = run("git status --porcelain")
    except:
        return []

    files = []

    for line in output.splitlines():
        file = line[3:]

        if not any(x in file for x in IGNORE):
            files.append(file)

    return files


def get_diff(file):
    try:
        return run(f'git diff "{file}"')
    except:
        return ""


def get_hash(file):
    try:
        with open(file, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()
    except:
        return None


# ═════════════════════════════════════════════════════════════
# SMART COMMIT MSGS
# ═════════════════════════════════════════════════════════════

def generate_commit_message(file, diff):
    lower = file.lower()

    additions = diff.count("\n+")
    deletions = diff.count("\n-")

    if "judge" in lower:
        return "feat(judge): improve execution engine"

    if "auth" in lower or "login" in lower:
        return "fix(auth): improve authentication"

    if "problem" in lower:
        return "ui(problem): refine testcase rendering"

    if "verdict" in lower:
        return "ui(verdict): improve verdict display"

    if lower.endswith(".jsx"):
        if additions > deletions:
            return f"ui: enhance {os.path.basename(file)}"

        return f"ui: refine {os.path.basename(file)}"

    if lower.endswith(".py"):
        return f"backend: improve {os.path.basename(file)}"

    if lower.endswith(".js"):
        return f"core: update {os.path.basename(file)}"

    if lower.endswith(".css"):
        return f"style: improve {os.path.basename(file)}"

    return f"chore: update {os.path.basename(file)}"


# ═════════════════════════════════════════════════════════════
# COMMIT
# ═════════════════════════════════════════════════════════════

def commit_file(file):
    global pending_push
    global commit_count

    current_hash = get_hash(file)

    if current_hash == last_hashes.get(file):
        return

    diff = get_diff(file)

    if not diff.strip():
        return

    commit_msg = generate_commit_message(file, diff)

    silent(f'git add "{file}"')

    commit = silent(
        f'git commit -m "{commit_msg}" "{file}"'
    )

    if commit.returncode == 0:

        commit_count += 1

        recent_commits.appendleft({
            "msg": commit_msg,
            "file": file,
            "time": ts()
        })

        log(
            f"Committed {os.path.basename(file)}",
            C.BRIGHT_GREEN
        )

        last_hashes[file] = current_hash

        pending_push = True


# ═════════════════════════════════════════════════════════════
# PUSH
# ═════════════════════════════════════════════════════════════

def push_changes():
    global pending_push
    global last_push
    global push_count

    push = silent("git push")

    if push.returncode == 0:

        push_count += 1

        log(
            "Changes synced to GitHub",
            C.BRIGHT_CYAN
        )

        pending_push = False
        last_push = time.time()

    else:
        log(
            "Push failed",
            C.BRIGHT_RED
        )


# ═════════════════════════════════════════════════════════════
# UI TABLES
# ═════════════════════════════════════════════════════════════

def line(width=96):
    return c("━" * width, C.DIM)


def table(title, rows, color=C.BRIGHT_CYAN):
    width = 96

    print(c(f"┏{'━' * (width - 2)}┓", C.DIM))

    print(
        c("┃ ", C.DIM) +
        c(title.ljust(width - 4), C.BOLD, color) +
        c(" ┃", C.DIM)
    )

    print(c(f"┣{'━' * (width - 2)}┫", C.DIM))

    for row in rows:
        row = row[:width - 6]

        print(
            c("┃ ", C.DIM) +
            row.ljust(width - 4) +
            c(" ┃", C.DIM)
        )

    print(c(f"┗{'━' * (width - 2)}┛", C.DIM))


# ═════════════════════════════════════════════════════════════
# RENDER
# ═════════════════════════════════════════════════════════════

def render():
    global spinner_index

    clear()

    spinner = SPINNER[spinner_index % len(SPINNER)]
    spinner_index += 1

    print()

    print(
        c("   SIMUX ", C.BOLD, C.BRIGHT_MAGENTA) +
        c("SMART GIT DAEMON", C.BOLD, C.BRIGHT_CYAN) +
        c(f"   {spinner}", C.BRIGHT_GREEN)
    )

    print(line())

    # STATUS TABLE

    rows = [
        f"{c('Repository', C.BRIGHT_MAGENTA)}  →  {c(os.getcwd(), C.BRIGHT_WHITE)}",
        f"{c('Branch', C.BRIGHT_MAGENTA)}      →  {c(get_branch(), C.BRIGHT_GREEN)}",
        f"{c('Commits', C.BRIGHT_MAGENTA)}     →  {c(commit_count, C.BRIGHT_CYAN)}",
        f"{c('Pushes', C.BRIGHT_MAGENTA)}      →  {c(push_count, C.BRIGHT_CYAN)}",
        f"{c('Queue', C.BRIGHT_MAGENTA)}       →  {c('PENDING PUSH', C.BRIGHT_YELLOW) if pending_push else c('IDLE', C.BRIGHT_GREEN)}",
        f"{c('Last Push', C.BRIGHT_MAGENTA)}   →  {c(datetime.fromtimestamp(last_push).strftime('%H:%M:%S'), C.BRIGHT_WHITE)}"
    ]

    table("SYSTEM STATUS", rows)

    # CHANGED FILES

    changed_rows = []

    for file in list(changed_files_live)[:8]:
        changed_rows.append(
            f"{c('MODIFIED', C.BRIGHT_YELLOW)}  →  {c(file, C.BRIGHT_WHITE)}"
        )

    if not changed_rows:
        changed_rows.append(
            c("No active file changes", C.DIM)
        )

    table(
        "LIVE FILE WATCHER",
        changed_rows,
        C.BRIGHT_YELLOW
    )

    # COMMITS

    commit_rows = []

    for commit in recent_commits:

        commit_rows.append(
            f"{c(commit['time'], C.DIM)}  {c(commit['msg'], C.BRIGHT_GREEN)}"
        )

    if not commit_rows:
        commit_rows.append(
            c("No commits yet", C.DIM)
        )

    table(
        "RECENT COMMITS",
        commit_rows,
        C.BRIGHT_GREEN
    )

    # LOGS

    log_rows = list(recent_logs)

    if not log_rows:
        log_rows.append(
            c("Daemon initialized", C.BRIGHT_CYAN)
        )

    table(
        "LIVE EVENT LOGS",
        log_rows,
        C.BRIGHT_MAGENTA
    )

    print()
    print(
        c(
            " CTRL + C ",
            C.BOLD,
            C.BRIGHT_RED
        ) +
        c("to stop daemon", C.DIM)
    )

    print()


# ═════════════════════════════════════════════════════════════
# STARTUP
# ═════════════════════════════════════════════════════════════

log(
    "Git daemon initialized",
    C.BRIGHT_CYAN
)

log(
    f"Watching {os.getcwd()}",
    C.BRIGHT_GREEN
)

# ═════════════════════════════════════════════════════════════
# MAIN LOOP
# ═════════════════════════════════════════════════════════════

while True:

    try:

        changed = get_changed_files()

        changed_files_live.clear()

        for file in changed:
            changed_files_live.appendleft(file)

        for file in changed:
            commit_file(file)

        if pending_push:

            now = time.time()

            if now - last_push >= PUSH_INTERVAL:
                push_changes()

        render()

        time.sleep(1)

    except KeyboardInterrupt:

        clear()

        print()

        print(
            c(
                " SMART PUSHER STOPPED ",
                C.BOLD,
                C.BRIGHT_RED
            )
        )

        print()

        break

    except Exception as e:

        log(
            f"{type(e).__name__}: {e}",
            C.BRIGHT_RED
        )

        render()

        time.sleep(2)