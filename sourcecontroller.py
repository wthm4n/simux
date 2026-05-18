import subprocess
import time
from datetime import datetime

last_commit = ""

IGNORE = {
    ".git",
    "__pycache__",
    "venv",
    "node_modules"
}


def run(cmd):
    return subprocess.check_output(cmd, shell=True, text=True).strip()


while True:
    try:
        status = run("git status --porcelain")

        if status:
            files = []

            for line in status.splitlines():
                parts = line.strip().split()
                if len(parts) >= 2:
                    file = parts[-1]

                    if not any(ignore in file for ignore in IGNORE):
                        files.append(file)

            if files:
                short_files = ", ".join(files[:5])

                commit_message = f"Updated {short_files}"

                if len(files) > 5:
                    commit_message += f" and {len(files)-5} more files"

                if commit_message != last_commit:
                    print(f"[{datetime.now()}] Committing: {commit_message}")

                    subprocess.run("git add .", shell=True)
                    subprocess.run(f'git commit -m "{commit_message}"', shell=True)
                    subprocess.run("git push", shell=True)

                    last_commit = commit_message

        time.sleep(2)

    except Exception as e:
        print(e)
        time.sleep(2)
