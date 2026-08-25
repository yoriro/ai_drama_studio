import asyncio
import errno
import logging
import time
from pathlib import Path


logger = logging.getLogger("app.trash")


def cleanup_expired_trash(data_dir: Path, retention_hours: int) -> None:
    trash_root = (data_dir / "trash").resolve()
    if not trash_root.exists():
        return
    if not trash_root.is_dir():
        raise NotADirectoryError(str(trash_root))

    cutoff = time.time() - retention_hours * 60 * 60
    for path in trash_root.rglob("*"):
        if path.is_file() and path.stat().st_mtime < cutoff:
            path.unlink()

    directories = [path for path in trash_root.rglob("*") if path.is_dir()]
    directories.sort(key=lambda path: len(path.parts), reverse=True)
    for path in directories:
        try:
            path.rmdir()
        except OSError as exc:
            if exc.errno not in {errno.ENOTEMPTY, errno.EEXIST}:
                raise


async def run_trash_cleanup_loop(data_dir: Path, retention_hours: int) -> None:
    try:
        while True:
            await asyncio.sleep(24 * 60 * 60)
            cleanup_expired_trash(data_dir, retention_hours)
    except asyncio.CancelledError:
        raise
    except OSError:
        logger.exception("Scheduled trash cleanup failed")
        raise
