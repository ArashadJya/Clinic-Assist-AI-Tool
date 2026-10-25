# check_before_push.py
# Safety check. Run it AFTER `git add .` and BEFORE `git commit` / `git push`:
#     python check_before_push.py
# It makes sure secrets are not going to GitHub and the project layout is correct.

import re           # to search for key-like text
import subprocess   # to ask git which files are staged
import sys

BLOCKED_NAMES = {".env", "secrets.toml", "clinic_log.csv"}   # must never be pushed
KEY_PATTERN = re.compile(r"AIza[0-9A-Za-z_\-]{10,}|AQ\.[0-9A-Za-z_\-]{10,}")  # API-key look-alikes
REQUIRED = ["app.py", "ai_engine.py", "logger.py", "sample_data.py", "requirements.txt"]


def staged_files():
    """List of files git will upload (staged or committed)."""
    result = subprocess.run(["git", "ls-files"], capture_output=True, text=True)
    if result.returncode != 0:
        print("X This folder is not a git repository. Run 'git init' first.")
        sys.exit(2)
    return [f for f in result.stdout.splitlines() if f]


def main():
    files = staged_files()
    problems = []

    if not files:
        problems.append("No files are staged. Run 'git add .' first.")

    for name in REQUIRED:                                    # app.py must be at the repo root
        if name not in files:
            problems.append(f"{name} is missing from the repo root "
                            "(files may be inside a sub-folder).")

    for path in files:
        base = path.split("/")[-1]
        if base in BLOCKED_NAMES:                            # secret or log file staged
            problems.append(f"{path} must NOT be uploaded. Remove it: git rm --cached {path}")
        try:
            text = open(path, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        if KEY_PATTERN.search(text):                         # key-like text inside a file
            problems.append(f"{path} contains text that looks like an API key.")

    if problems:
        print("X NOT SAFE TO PUSH:")
        for p in problems:
            print("  -", p)
        sys.exit(1)
    print(f"OK: {len(files)} files are ready to push. No secrets found.")


if __name__ == "__main__":
    main()
