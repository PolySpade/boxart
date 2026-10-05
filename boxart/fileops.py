"""Filesystem moves that never replace an existing destination."""
from __future__ import annotations

import ctypes
import ctypes.util
import errno
import os

_RENAME_NOREPLACE = 1
_AT_FDCWD = -100
try:
    _libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    _renameat2 = _libc.renameat2
    _renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
except (OSError, AttributeError, TypeError):
    _renameat2 = None


def move_no_replace(source: os.PathLike | str, target: os.PathLike | str) -> None:
    """Rename within one filesystem, failing with FileExistsError if target exists.

    os.rename silently replaces files on Linux, so prefer renameat2(RENAME_NOREPLACE),
    which ext4, btrfs, vfat and exfat support. Other filesystems fall back to a
    check-then-rename, which is only safe against other BoxArt writes.
    """
    src, dst = os.fsencode(source), os.fsencode(target)
    if _renameat2 is not None:
        if _renameat2(_AT_FDCWD, src, _AT_FDCWD, dst, _RENAME_NOREPLACE) == 0:
            return
        code = ctypes.get_errno()
        if code not in (errno.EINVAL, errno.ENOSYS, errno.EOPNOTSUPP):
            raise OSError(code, os.strerror(code), os.fsdecode(dst))
    if os.path.lexists(dst):
        raise FileExistsError(errno.EEXIST, os.strerror(errno.EEXIST), os.fsdecode(dst))
    os.rename(src, dst)
