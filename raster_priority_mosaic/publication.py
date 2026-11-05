"""Owned staging and Linux atomic, no-replace directory publication."""
from contextlib import contextmanager
import ctypes
import errno
import os
from pathlib import Path
import shutil
import sys
import tempfile

from .model import MosaicError, destination_path


def rename_no_replace(source, destination):
    if sys.platform != "linux":
        raise MosaicError("atomic publication requires Linux renameat2 support")
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        rename = libc.renameat2
    except AttributeError as exc:
        raise MosaicError("libc does not expose renameat2; no unsafe fallback is used") from exc
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1) != 0:
        code = ctypes.get_errno()
        if code in (errno.EEXIST, errno.ENOTEMPTY):
            raise MosaicError("destination already exists; nothing was replaced")
        raise MosaicError(f"no-replace directory rename failed: {os.strerror(code)}")


def same_inode(path, identity):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return (info.st_dev, info.st_ino) == identity


@contextmanager
def staged_directory(destination):
    """Publish only on normal exit. Parent directories must be trusted and stable."""
    dest = destination_path(destination)
    if sys.platform != "linux":
        raise MosaicError("this version publishes only on Linux")
    lock = dest.parent / ("." + dest.name + ".rpm-lock")
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise MosaicError("destination has a writer lock; stale locks require manual inspection") from exc
    lock_info = os.fstat(fd)
    lock_identity = (lock_info.st_dev, lock_info.st_ino)
    stage = None
    stage_identity = None
    try:
        if dest.exists():
            raise MosaicError("destination already exists; nothing was replaced")
        stage = Path(tempfile.mkdtemp(prefix=".rpm-stage-", dir=dest.parent))
        info = stage.stat()
        stage_identity = (info.st_dev, info.st_ino)
        yield stage
        rename_no_replace(stage, dest)
        stage = None
    finally:
        try:
            if stage is not None and same_inode(stage, stage_identity):
                shutil.rmtree(stage)
        finally:
            os.close(fd)
            if same_inode(lock, lock_identity):
                lock.unlink()
