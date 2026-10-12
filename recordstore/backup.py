"""Consistent SQLite snapshots via the backup API."""

import os
import sqlite3
import sys


def backup_database(src_path: str, dest_path: str) -> None:
    src_abs = os.path.abspath(src_path)
    dest_abs = os.path.abspath(dest_path)
    if not os.path.isfile(src_abs):
        raise FileNotFoundError(src_path)
    if src_abs == dest_abs:
        raise ValueError("destination must differ from source")
    parent = os.path.dirname(dest_abs)
    if parent:
        os.makedirs(parent, exist_ok=True)
    if os.path.exists(dest_abs):
        raise FileExistsError(dest_path)

    src = sqlite3.connect(src_abs, timeout=5)
    dest = None
    try:
        src.execute("PRAGMA busy_timeout = 5000")
        dest = sqlite3.connect(dest_abs)
        src.backup(dest)
    except Exception:
        if dest is not None:
            dest.close()
            dest = None
        if os.path.exists(dest_abs):
            os.remove(dest_abs)
        raise
    finally:
        if dest is not None:
            dest.close()
        src.close()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        sys.stderr.write("usage: python -m recordstore.backup SRC DEST\n")
        return 2
    try:
        backup_database(args[0], args[1])
    except FileNotFoundError:
        sys.stderr.write("backup source not found\n")
        return 1
    except FileExistsError:
        sys.stderr.write("backup destination exists\n")
        return 1
    except ValueError:
        sys.stderr.write("backup destination must be a different path\n")
        return 1
    except Exception:
        sys.stderr.write("backup failed\n")
        return 1
    sys.stdout.write("backup written\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
