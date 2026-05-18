import subprocess
import time
import threading
import itertools
import os
import sys
from datetime import datetime

# ─────────────────────────────────────────────────────────────
# Terminal UI
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


def divider(char="━", width=72):
    print(c(char * width, C.DIM))


def header(title):
    divider()

    print(
        c(" SIMUX AUTO PUSHER ", C.BOLD, C.BRIGHT_MAGENTA) +
        c(f" {title}", C.BRIGHT_CYAN)
    )

    divider()


def log(level, msg):
    icons = {
        "info": ("●", C.BRIGHT_BLUE),
        "ok": ("✔", C.BRIGHT_GREEN),
        "warn": ("⚠", C.BRIGHT_YELLOW),
        "error": ("✖", C.BRIGHT_RED),
        "git": ("◆", C.BRIGHT_MAGENTA),
        "push": ("⬆", C.BRIGHT_CYAN),
    }

    icon, color = icons.get(level, ("•", C.WHITE))

    print(
        f" {ts()} {c(icon, color)} {msg}"
    )


# ─────────────────────────────────────────────────────────────
# Spinner
# ─────────────────────────────────────────────────────────────

class Spinner:
    FRAMES = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]

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

        sys.stdout.write("\r" + " " * (len(self.label) + 10) + "\r")
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
# Config
# ─────────────────────────────────────────────────────────────

last_commit = ""

IGNORE = {
    ".git",
    "__pycache__",
    "venv",
    "node_modules",
    ".next",
    "dist",
    "build",
}


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def run(cmd, capture=True):
    if capture:
        return subprocess.check_output(
            cmd,
            shell=True,
            text=True
        ).strip()

    return subprocess.run(cmd, shell=True)


def generate_commit_message(files):
    categorized = {
        "frontend": [],
        "backend": [],
        "config": [],
        "docs": [],
        "other": [],
    }

    for file in files:
        lower = file.lower()

        if any(x in lower for x in ["react", "tailwind", "component", "page", "frontend"]):
            categorized["frontend"].append(file)

        elif any(x in lower for x in ["api", "server", "backend", "judge", "worker"]):
            categorized["backend"].append(file)

        elif any(x in lower for x in [".json", ".env", "config"]):
            categorized["config"].append(file)

        elif any(x in lower for x in ["readme", ".md", "docs"]):
            categorized["docs"].append(file)

        else:
            categorized["other"].append(file)

    parts = []

    for category, arr in categorized.items():
        if arr:
            parts.append(category)

    if not parts:
        return "Minor project updates"

    return f"Updated {' + '.join(parts)} modules"


# ─────────────────────────────────────────────────────────────
# Startup
# ─────────────────────────────────────────────────────────────

header("Git Automation Service")

log(
    "info",
    f"Watching repository → {c(os.getcwd(), C.BRIGHT_CYAN)}"
)

log(
    "info",
    f"Branch → {c(run('git branch --show-current'), C.BRIGHT_GREEN)}"
)

divider()

# ─────────────────────────────────────────────────────────────
# Main Loop
# ─────────────────────────────────────────────────────────────

while True:
    try:
        status = run("git status --porcelain")

        if status:
            changed_files = []

            for line in status.splitlines():
                parts = line.strip().split()

                if len(parts) >= 2:
                    file = parts[-1]

                    if not any(ignore in file for ignore in IGNORE):
                        changed_files.append(file)

            if changed_files:
                short = ", ".join(changed_files[:4])

                log(
                    "git",
                    f"Changes detected → {c(short, C.BRIGHT_YELLOW)}"
                )

                if len(changed_files) > 4:
                    log(
                        "dim",
                        f"+ {len(changed_files) - 4} more files"
                    )

                commit_message = generate_commit_message(changed_files)

                if commit_message != last_commit:

                    spinner = Spinner(
                        "Staging, committing & pushing..."
                    ).start()

                    subprocess.run(
                        "git add .",
                        shell=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )

                    commit = subprocess.run(
                        f'git commit -m "{commit_message}"',
                        shell=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )

                    if commit.returncode == 0:

                        push = subprocess.run(
                            "git push",
                            shell=True,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL
                        )

                        spinner.stop(
                            push.returncode == 0,
                            "Changes synced to GitHub"
                            if push.returncode == 0
                            else "Push failed"
                        )

                        if push.returncode == 0:
                            log(
                                "push",
                                f"Commit → {c(commit_message, C.BRIGHT_MAGENTA)}"
                            )

                            log(
                                "ok",
                                f"Files synced → {c(len(changed_files), C.BRIGHT_GREEN)}"
                            )

                            divider()

                            last_commit = commit_message

                    else:
                        spinner.stop(False, "Nothing new to commit")

        time.sleep(2)

    except KeyboardInterrupt:
        print()

        divider()

        log(
            "warn",
            "Auto pusher stopped by user"
        )

        divider()

        break

    except Exception as e:
        log(
            "error",
            f"{type(e).__name__}: {e}"
        )

        time.sleep(2)