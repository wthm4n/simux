import subprocess
import time
import threading
import itertools
import hashlib
import sys
import os
from datetime import datetime

# ─────────────────────────────────────────────────────────────
# COLORS / UI
# ─────────────────────────────────────────────────────────────

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


def ts():
    return c(f"[{datetime.now().strftime('%H:%M:%S')}]", C.DIM)


def divider(char="━", width=84):
    print(c(char * width, C.DIM))


def header(title):
    divider()

    print(
        c(" SIMUX SMART PUSHER ", C.BOLD, C.BRIGHT_MAGENTA) +
        c(f" {title}", C.BRIGHT_CYAN)
    )

    divider()


def box(title, rows):
    width = 84

    print(c(f"┏{'━' * (width - 2)}┓", C.DIM))
    print(
        c("┃ ", C.DIM) +
        c(title.ljust(width - 4), C.BOLD, C.BRIGHT_CYAN) +
        c(" ┃", C.DIM)
    )
    print(c(f"┣{'━' * (width - 2)}┫", C.DIM))

    for row in rows:
        clean = row[:width - 6]
        print(
            c("┃ ", C.DIM) +
            clean.ljust(width - 4) +
            c(" ┃", C.DIM)
        )

    print(c(f"┗{'━' * (width - 2)}┛", C.DIM))


def log(level, msg):
    icons = {
        "info": ("●", C.BRIGHT_BLUE),
        "ok": ("✔", C.BRIGHT_GREEN),
        "warn": ("⚠", C.BRIGHT_YELLOW),
        "error": ("✖", C.BRIGHT_RED),
        "git": ("◆", C.BRIGHT_MAGENTA),
        "push": ("⬆", C.BRIGHT_CYAN),
        "commit": ("⬤", C.BRIGHT_GREEN),
    }

    icon, color = icons.get(level, ("•", C.WHITE))

    print(
        f" {ts()} {c(icon, color)} {msg}"
    )


# ─────────────────────────────────────────────────────────────
# SPINNER
# ─────────────────────────────────────────────────────────────

class Spinner:
    FRAMES = [
        "⠋","⠙","⠹","⠸","⠼",
        "⠴","⠦","⠧","⠇","⠏"
    ]

    def __init__(self, label):
        self.label = label
        self.stop_event = threading.Event()

        self.thread = threading.Thread(
            target=self.animate,
            daemon=True
        )

    def animate(self):
        for frame in itertools.cycle(self.FRAMES):

            if self.stop_event.is_set():
                break

            sys.stdout.write(
                f"\r {c(frame, C.BRIGHT_CYAN)} {c(self.label, C.DIM)}"
            )

            sys.stdout.flush()

            time.sleep(0.08)

        sys.stdout.write("\r" + " " * 120 + "\r")
        sys.stdout.flush()

    def start(self):
        self.thread.start()
        return self

    def stop(self, ok=True, final=None):
        self.stop_event.set()
        self.thread.join()

        icon = (
            c("✔", C.BRIGHT_GREEN)
            if ok else
            c("✖", C.BRIGHT_RED)
        )

        print(f" {icon} {final or self.label}")


# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────

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
pending_push = False
last_push = time.time()

# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

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


def get_changed_files():
    try:
        status = run("git status --porcelain")
    except:
        return []

    files = []

    for line in status.splitlines():
        file = line[3:]

        if not any(x in file for x in IGNORE):
            files.append(file)

    return files


def get_hash(file):
    try:
        with open(file, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()
    except:
        return None


def get_diff(file):
    try:
        return run(f'git diff "{file}"')
    except:
        return ""


# ─────────────────────────────────────────────────────────────
# SMART COMMIT MSG
# ─────────────────────────────────────────────────────────────

def generate_commit_message(file, diff):
    lower = file.lower()

    additions = diff.count("\n+")
    deletions = diff.count("\n-")

    if "judge" in lower:
        return "feat(judge): improve execution handling"

    if "auth" in lower or "login" in lower:
        return "fix(auth): improve authentication flow"

    if lower.endswith(".jsx"):
        if additions > deletions:
            return f"ui: enhance {os.path.basename(file)}"

        return f"ui: refine {os.path.basename(file)}"

    if lower.endswith(".py"):
        return f"backend: update {os.path.basename(file)}"

    if lower.endswith(".js"):
        return f"core: improve {os.path.basename(file)}"

    if lower.endswith(".css"):
        return f"style: update {os.path.basename(file)}"

    return f"chore: modify {os.path.basename(file)}"


# ─────────────────────────────────────────────────────────────
# COMMIT SINGLE FILE
# ─────────────────────────────────────────────────────────────

def commit_file(file):
    global pending_push

    current_hash = get_hash(file)

    if current_hash == last_hashes.get(file):
        return

    diff = get_diff(file)

    if not diff.strip():
        return

    commit_msg = generate_commit_message(file, diff)

    spinner = Spinner(
        f"Committing {os.path.basename(file)}..."
    ).start()

    silent(f'git add "{file}"')

    commit = silent(
        f'git commit -m "{commit_msg}" "{file}"'
    )

    if commit.returncode == 0:

        spinner.stop(
            True,
            f"Committed {os.path.basename(file)}"
        )

        box(
            "NEW COMMIT",
            [
                f"{c('FILE', C.BRIGHT_MAGENTA)}     → {c(file, C.BRIGHT_WHITE)}",
                f"{c('MESSAGE', C.BRIGHT_CYAN)}  → {c(commit_msg, C.BRIGHT_GREEN)}",
                f"{c('STATUS', C.BRIGHT_YELLOW)}   → {c('SYNC QUEUED', C.BRIGHT_YELLOW)}",
            ]
        )

        last_hashes[file] = current_hash

        pending_push = True

    else:
        spinner.stop(False, f"Skipped {file}")


# ─────────────────────────────────────────────────────────────
# STARTUP
# ─────────────────────────────────────────────────────────────

header("Git Automation Service")

log(
    "info",
    f"Repository → {c(os.getcwd(), C.BRIGHT_CYAN)}"
)

log(
    "info",
    f"Branch → {c(run('git branch --show-current'), C.BRIGHT_GREEN)}"
)

divider()

# ─────────────────────────────────────────────────────────────
# LOOP
# ─────────────────────────────────────────────────────────────

while True:

    try:
        changed = get_changed_files()

        if changed:

            box(
                "DETECTED CHANGES",
                [
                    f"{c('FILES', C.BRIGHT_MAGENTA)} → {c(', '.join(changed[:5]), C.BRIGHT_WHITE)}"
                ]
            )

            for file in changed:
                commit_file(file)

        if pending_push:

            now = time.time()

            if now - last_push >= PUSH_INTERVAL:

                spinner = Spinner(
                    "Pushing commits to GitHub..."
                ).start()

                push = silent("git push")

                spinner.stop(
                    push.returncode == 0,
                    "GitHub sync complete"
                    if push.returncode == 0
                    else "Push failed"
                )

                if push.returncode == 0:

                    box(
                        "REMOTE SYNC",
                        [
                            f"{c('STATUS', C.BRIGHT_GREEN)} → {c('ALL COMMITS PUSHED', C.BRIGHT_GREEN)}",
                            f"{c('TIME', C.BRIGHT_CYAN)}   → {c(datetime.now().strftime('%H:%M:%S'), C.BRIGHT_WHITE)}"
                        ]
                    )

                    pending_push = False
                    last_push = now

        time.sleep(2)

    except KeyboardInterrupt:

        print()

        divider()

        log(
            "warn",
            "Smart pusher stopped"
        )

        divider()

        break

    except Exception as e:

        log(
            "error",
            f"{type(e).__name__}: {e}"
        )

        time.sleep(2)