"""Keep the data folder safe on hosts with no permanent disk, such as a free Hugging Face Space.

With HF_BACKUP_REPO and HF_TOKEN set, the data folder is copied to a private dataset
repo after every round and restored from it on startup. Without them, this does nothing.

    python -m backend.backup restore     # run before the app starts
"""

import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from .config import DATA_DIR, HF_BACKUP_REPO, HF_TOKEN

SKIP_SUFFIXES = ("-wal", "-shm", "-journal", ".lock")
RESTORE_FAILED = DATA_DIR / ".restore-failed"


def enabled() -> bool:
    return bool(HF_BACKUP_REPO and HF_TOKEN)


def _copy_database(source: Path, target: Path):
    """A consistent copy of a live SQLite file, including anything still in its write-ahead log."""
    with sqlite3.connect(source) as live, sqlite3.connect(target) as copy:
        live.backup(copy)
    copy.close()
    live.close()


def _snapshot(folder: Path):
    """Copy the data folder into `folder`, taking SQLite files through the backup API."""
    for path in DATA_DIR.rglob("*"):
        if path.is_dir() or path.name.endswith(SKIP_SUFFIXES):
            continue
        target = folder / path.relative_to(DATA_DIR)
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix in (".db", ".sqlite"):
            try:
                _copy_database(path, target)
                continue
            except sqlite3.Error:
                pass  # not a database after all, or busy: fall back to a plain copy
        shutil.copy2(path, target)


def save() -> bool:
    """Upload a snapshot of the data folder. Returns whether a backup was made."""
    if not enabled():
        return False
    if RESTORE_FAILED.exists():
        print("Backup skipped: the last restore failed, so the stored backup is being kept", file=sys.stderr)
        return False
    try:
        from huggingface_hub import HfApi

        api = HfApi(token=HF_TOKEN)
        api.create_repo(HF_BACKUP_REPO, repo_type="dataset", private=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as folder:
            _snapshot(Path(folder))
            api.upload_folder(
                folder_path=folder, repo_id=HF_BACKUP_REPO, repo_type="dataset",
                commit_message="Trading floor backup", delete_patterns=["*"],
            )
        return True
    except Exception as e:
        print(f"Backup failed: {e}", file=sys.stderr)
        return False


def restore() -> bool:
    """Fill an empty data folder from the last backup. Never overwrites existing accounts."""
    if not enabled():
        return False
    if (DATA_DIR / "accounts.db").exists():
        print("Data already present; not restoring", file=sys.stderr)
        return False
    from huggingface_hub import snapshot_download
    from huggingface_hub.errors import RepositoryNotFoundError

    try:
        snapshot_download(HF_BACKUP_REPO, repo_type="dataset", local_dir=str(DATA_DIR), token=HF_TOKEN)
    except RepositoryNotFoundError:
        print("No backup exists yet; starting fresh", file=sys.stderr)
        return False
    except Exception as e:
        # A backup may exist but could not be read. Starting blank and saving over it would
        # destroy it, so leave a marker that stops save() and report the failure.
        RESTORE_FAILED.write_text(str(e)[:500], encoding="utf-8")
        print(f"Restore failed ({e}); backups are disabled until a restore succeeds", file=sys.stderr)
        raise
    shutil.rmtree(DATA_DIR / ".cache", ignore_errors=True)
    RESTORE_FAILED.unlink(missing_ok=True)
    print("Restored data from backup", file=sys.stderr)
    return True


if __name__ == "__main__":
    if sys.argv[1:] == ["restore"]:
        try:
            restore()
        except Exception:
            sys.exit(1)
    elif sys.argv[1:] == ["save"]:
        print("Backed up" if save() else "No backup made")
    else:
        print(__doc__)
