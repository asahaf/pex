# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import errno
import os
from contextlib import contextmanager

import pytest

from pex.atomic_directory import AtomicDirectory, FileLockStyle, _is_bsd_lock, atomic_directory
from pex.common import temporary_dir, touch
from pex.typing import TYPE_CHECKING
from testing import environment_as

try:
    from unittest import mock
except ImportError:
    import mock  # type: ignore[no-redef,import]

if TYPE_CHECKING:
    from typing import Iterator, Optional, Type


def test_is_bsd_lock():
    # type: () -> None

    assert not _is_bsd_lock(
        lock_style=None
    ), "Expected the default lock style to be POSIX for maximum compatibility."
    assert not _is_bsd_lock(lock_style=FileLockStyle.POSIX)
    assert _is_bsd_lock(lock_style=FileLockStyle.BSD)

    # The hard-coded default is already POSIX, so setting the env var default changes nothing.
    with environment_as(_PEX_FILE_LOCK_STYLE="posix"):
        assert not _is_bsd_lock(lock_style=None)
        assert not _is_bsd_lock(lock_style=FileLockStyle.POSIX)
        assert _is_bsd_lock(lock_style=FileLockStyle.BSD)

    with environment_as(_PEX_FILE_LOCK_STYLE="bsd"):
        assert _is_bsd_lock(
            lock_style=None
        ), "Expected the default lock style to be taken from the environment when defined."
        assert not _is_bsd_lock(lock_style=FileLockStyle.POSIX)
        assert _is_bsd_lock(lock_style=FileLockStyle.BSD)


@contextmanager
def maybe_raises(exception=None):
    # type: (Optional[Type[Exception]]) -> Iterator[None]
    @contextmanager
    def noop():
        yield

    context = noop() if exception is None else pytest.raises(exception)
    with context:
        yield


def atomic_directory_finalize_test(errno, expect_raises=None):
    # type: (int, Optional[Type[Exception]]) -> None
    with mock.patch("os.rename", spec_set=True, autospec=True) as mock_rename:
        mock_rename.side_effect = OSError(errno, os.strerror(errno))
        with maybe_raises(expect_raises):
            AtomicDirectory("to.dir").finalize()


def test_atomic_directory_finalize_eexist():
    # type: () -> None
    atomic_directory_finalize_test(errno.EEXIST)


def test_atomic_directory_finalize_enotempty():
    # type: () -> None
    atomic_directory_finalize_test(errno.ENOTEMPTY)


def test_atomic_directory_finalize_eperm():
    # type: () -> None
    atomic_directory_finalize_test(errno.EPERM, expect_raises=OSError)


def test_atomic_directory_empty_workdir_finalize():
    # type: () -> None
    with temporary_dir() as sandbox:
        target_dir = os.path.join(sandbox, "target_dir")
        assert not os.path.exists(target_dir)

        with atomic_directory(target_dir) as atomic_dir:
            assert not atomic_dir.is_finalized()
            assert target_dir == atomic_dir.target_dir
            assert os.path.exists(atomic_dir.work_dir)
            assert os.path.isdir(atomic_dir.work_dir)
            assert [] == os.listdir(atomic_dir.work_dir)

            touch(os.path.join(atomic_dir.work_dir, "created"))

            assert not os.path.exists(target_dir)

        assert not os.path.exists(atomic_dir.work_dir), "The work_dir should always be cleaned up."
        assert os.path.exists(os.path.join(target_dir, "created"))


def test_atomic_directory_empty_workdir_failure():
    # type: () -> None
    class SimulatedRuntimeError(RuntimeError):
        pass

    with temporary_dir() as sandbox:
        target_dir = os.path.join(sandbox, "target_dir")
        with pytest.raises(SimulatedRuntimeError):
            with atomic_directory(target_dir) as atomic_dir:
                assert not atomic_dir.is_finalized()
                touch(os.path.join(atomic_dir.work_dir, "created"))
                raise SimulatedRuntimeError()

        assert not os.path.exists(  # type: ignore[unreachable]
            atomic_dir.work_dir
        ), "The work_dir should always be cleaned up."
        assert not os.path.exists(target_dir), (
            "When the context raises the work_dir it was given should not be moved to the "
            "target_dir."
        )


def test_atomic_directory_empty_workdir_finalized():
    # type: () -> None
    with temporary_dir() as target_dir:
        with atomic_directory(target_dir) as work_dir:
            assert (
                work_dir.is_finalized()
            ), "When the target_dir exists no work_dir should be created."


def test_atomic_directory_locked_mode():
    # type: () -> None

    assert AtomicDirectory("unlocked").work_dir != AtomicDirectory("unlocked").work_dir
    assert (
        AtomicDirectory("locked", locked=True).work_dir
        == AtomicDirectory("locked", locked=True).work_dir
    )
