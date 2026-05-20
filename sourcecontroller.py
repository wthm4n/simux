# pip install rich watchdog gitpython

import os
import time
import hashlib
import subprocess
from collections import deque

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.live import Live
from rich.align import Align
from rich.text import Text
from rich.columns import Columns

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

# ═════════════════════════════════════════════════════════════
# STATE
# ═════════════════════════════════════════════════════════════

console = Console()

recent_logs = deque(maxlen=10)
recent_commits = deque(maxlen=8)
changed_files = deque(maxlen=10)

last_hashes = {}

push_count = 0
commit_count = 0

pending_push = False
last_push = time.time()

# ═════════════════════════════════════════════════════════════
# HELPERS
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


def log(msg, style="cyan"):
    recent_logs.appendleft(
        f"[dim]{time.strftime('%H:%M:%S')}[/dim] [{style}]{msg}[/{style}]"
    )


def get_branch():
    try:
        return run("git branch --show-current")
    except:
        return "unknown"


def get_changed():
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


# ═════════════════════════════════════════════════════════════
# SMART COMMIT MESSAGE
# ═════════════════════════════════════════════════════════════

def generate_commit_message(file, diff):
    lower = file.lower()

    if "judge" in lower:
        return "feat(judge): improve execution engine"

    if "auth" in lower or "login" in lower:
        return "fix(auth): improve authentication"

    if "problem" in lower:
        return "ui(problem): refine testcase rendering"

    if "verdict" in lower:
        return "ui(verdict): improve verdict display"

    if lower.endswith(".jsx"):
        return f"ui: update {os.path.basename(file)}"

    if lower.endswith(".py"):
        return f"backend: improve {os.path.basename(file)}"

    if lower.endswith(".js"):
        return f"core: update {os.path.basename(file)}"

    if lower.endswith(".css"):
        return f"style: improve {os.path.basename(file)}"

    return f"chore: update {os.path.basename(file)}"


# ═════════════════════════════════════════════════════════════
# COMMIT LOGIC
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

    msg = generate_commit_message(file, diff)

    silent(f'git add "{file}"')

    commit = silent(
        f'git commit -m "{msg}" "{file}"'
    )

    if commit.returncode == 0:

        commit_count += 1

        recent_commits.appendleft(
            f"[green]{msg}[/green]"
        )

        log(
            f"Committed {os.path.basename(file)}",
            "green"
        )

        last_hashes[file] = current_hash

        pending_push = True


# ═════════════════════════════════════════════════════════════
# PUSH LOGIC
# ═════════════════════════════════════════════════════════════

def push_changes():
    global pending_push
    global last_push
    global push_count

    push = silent("git push")

    if push.returncode == 0:

        push_count += 1

        pending_push = False
        last_push = time.time()

        log(
            "Changes pushed to GitHub",
            "bright_cyan"
        )

    else:

        log(
            "Push failed",
            "red"
        )


# ═════════════════════════════════════════════════════════════
# UI COMPONENTS
# ═════════════════════════════════════════════════════════════

def make_status():
    table = Table.grid(expand=True)

    table.add_column(justify="left")
    table.add_column(justify="right")

    queue = (
        "[yellow]PENDING[/yellow]"
        if pending_push else
        "[green]IDLE[/green]"
    )

    table.add_row(
        "[bold magenta]Repository[/bold magenta]",
        os.getcwd()
    )

    table.add_row(
        "[bold magenta]Branch[/bold magenta]",
        f"[green]{get_branch()}[/green]"
    )

    table.add_row(
        "[bold magenta]Commits[/bold magenta]",
        f"[cyan]{commit_count}[/cyan]"
    )

    table.add_row(
        "[bold magenta]Pushes[/bold magenta]",
        f"[cyan]{push_count}[/cyan]"
    )

    table.add_row(
        "[bold magenta]Queue[/bold magenta]",
        queue
    )

    table.add_row(
        "[bold magenta]Last Push[/bold magenta]",
        time.strftime(
            "%H:%M:%S",
            time.localtime(last_push)
        )
    )

    return Panel(
        table,
        title="[bold bright_cyan]SYSTEM STATUS[/bold bright_cyan]",
        border_style="bright_blue"
    )


def make_files():
    table = Table(expand=True)

    table.add_column("Status", style="yellow")
    table.add_column("File", style="white")

    if changed_files:
        for file in list(changed_files)[:8]:
            table.add_row(
                "MODIFIED",
                file
            )
    else:
        table.add_row(
            "IDLE",
            "No changed files"
        )

    return Panel(
        table,
        title="[bold yellow]LIVE FILE WATCHER[/bold yellow]",
        border_style="yellow"
    )


def make_commits():
    table = Table(expand=True)

    table.add_column("Recent Commits", style="green")

    if recent_commits:
        for commit in recent_commits:
            table.add_row(commit)
    else:
        table.add_row("[dim]No commits yet[/dim]")

    return Panel(
        table,
        title="[bold green]RECENT COMMITS[/bold green]",
        border_style="green"
    )


def make_logs():
    table = Table(expand=True)

    table.add_column("Logs", style="cyan")

    if recent_logs:
        for row in recent_logs:
            table.add_row(row)
    else:
        table.add_row("[dim]Waiting for activity[/dim]")

    return Panel(
        table,
        title="[bold magenta]LIVE EVENT LOGS[/bold magenta]",
        border_style="magenta"
    )


# ═════════════════════════════════════════════════════════════
# MAIN LAYOUT
# ═════════════════════════════════════════════════════════════

def build_layout():

    layout = Layout()

    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="main"),
        Layout(name="footer", size=3)
    )

    layout["main"].split_row(
        Layout(name="left"),
        Layout(name="right")
    )

    layout["left"].split_column(
        Layout(name="status"),
        Layout(name="files")
    )

    layout["right"].split_column(
        Layout(name="commits"),
        Layout(name="logs")
    )

    # HEADER

    layout["header"].update(
        Panel(
            Align.center(
                Text(
                    "SIMUX SMART GIT DAEMON",
                    style="bold bright_magenta"
                )
            ),
            border_style="bright_cyan"
        )
    )

    # PANELS

    layout["status"].update(make_status())
    layout["files"].update(make_files())

    layout["commits"].update(make_commits())
    layout["logs"].update(make_logs())

    # FOOTER

    footer = Text()

    footer.append(
        " CTRL + C ",
        style="bold white on red"
    )

    footer.append(
        " to stop daemon",
        style="dim"
    )

    layout["footer"].update(
        Panel(
            Align.center(footer),
            border_style="bright_black"
        )
    )

    return layout


# ═════════════════════════════════════════════════════════════
# STARTUP
# ═════════════════════════════════════════════════════════════

log("Smart daemon initialized", "bright_cyan")
log(f"Watching {os.getcwd()}", "green")

# ═════════════════════════════════════════════════════════════
# MAIN LOOP
# ═════════════════════════════════════════════════════════════

with Live(
    build_layout(),
    refresh_per_second=10,
    screen=True
) as live:

    while True:

        try:

            changed = get_changed()

            changed_files.clear()

            for file in changed:
                changed_files.appendleft(file)

            for file in changed:
                commit_file(file)

            if pending_push:

                now = time.time()

                if now - last_push >= PUSH_INTERVAL:
                    push_changes()

            live.update(build_layout())

            time.sleep(1)

        except KeyboardInterrupt:
            break

        except Exception as e:

            log(
                f"{type(e).__name__}: {e}",
                "red"
            )

            live.update(build_layout())

            time.sleep(2)