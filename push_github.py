#!/usr/bin/env python3
"""Kirim semua perubahan di folder ini ke GitHub (add -> commit -> push).

Pakai:
    python3 push_github.py                 # pesan commit otomatis (tanggal & jam)
    python3 push_github.py "pesan saya"    # pesan commit sendiri
    python3 push_github.py --dry-run       # hanya tampilkan perubahan, tidak mengirim
"""
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent


def git(*args, check=True):
    result = subprocess.run(
        ["git", *args], cwd=REPO_DIR, text=True, capture_output=True
    )
    if check and result.returncode != 0:
        raise SystemExit(f"\n[GAGAL] git {' '.join(args)}\n{result.stderr.strip()}")
    return result.stdout.strip()


def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]
    message = args[0] if args else f"Update {datetime.now():%Y-%m-%d %H:%M}"

    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    changes = git("status", "--short")

    if not changes:
        print("Tidak ada perubahan untuk dikirim.")
        return

    print(f"Branch : {branch}")
    print(f"Pesan  : {message}")
    print("Perubahan:")
    print(changes)

    if dry_run:
        print("\n(dry-run: tidak ada yang dikirim)")
        return

    git("add", "-A")
    git("commit", "-m", message)
    git("push", "origin", branch)
    print("\nBerhasil dikirim ke GitHub.")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        print(e)
        sys.exit(1)
