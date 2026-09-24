"""One read-only interface over sealed JSONL and ``.jsonl.zst`` files.

Compressed files are only for immutable, already-finished journals. Callers still pass the
original ``turn_frames.jsonl`` path; when it is absent and a sibling ``.zst`` exists, this
module decompresses transparently.
Writers must not append compressed files through this module.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
from pathlib import Path
import subprocess
from typing import BinaryIO, Iterator


class CompressedJsonlError(RuntimeError):
    """The compressed JSONL is missing, corrupt, or cannot be decompressed."""


def compressed_path(path: Path) -> Path:
    return Path(f"{Path(path)}.zst")


def resolve_read_path(path: Path) -> Path:
    """Return whichever of the raw or zstd path exists; if neither does, return the raw path."""

    path = Path(path)
    if path.is_file():
        return path
    archived = compressed_path(path)
    if archived.is_file():
        return archived
    return path


def is_compressed_read_path(path: Path) -> bool:
    return resolve_read_path(path) == compressed_path(path)


@contextmanager
def open_binary(path: Path) -> Iterator[BinaryIO]:
    """Read JSONL fully as a binary stream; ``.zst`` is decompressed via the system zstd."""

    requested = Path(path)
    actual = resolve_read_path(requested)
    if not actual.is_file():
        raise FileNotFoundError(requested)
    if actual == requested:
        with actual.open("rb") as handle:
            yield handle
        return

    process = subprocess.Popen(
        ["zstd", "-q", "-d", "-c", "--", str(actual)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None
    assert process.stderr is not None
    try:
        yield process.stdout
    except BaseException:
        process.kill()
        process.wait()
        raise
    else:
        process.stdout.close()
        stderr = process.stderr.read().decode("utf-8", errors="replace")
        returncode = process.wait()
        if returncode != 0:
            raise CompressedJsonlError(
                f"zstd decompression failed for {actual}: rc={returncode}; "
                f"stderr={stderr.strip()}"
            )
    finally:
        process.stderr.close()


def iter_binary_lines(path: Path) -> Iterator[bytes]:
    with open_binary(path) as handle:
        yield from handle


def read_bytes(path: Path) -> bytes:
    with open_binary(path) as handle:
        return handle.read()


def read_text(path: Path, *, encoding: str = "utf-8") -> str:
    return read_bytes(path).decode(encoding)


def first_nonempty_line(path: Path) -> bytes:
    """Read the first non-empty line, consuming the whole stream to validate the compressed frame."""

    first: bytes | None = None
    for raw in iter_binary_lines(path):
        if first is None and raw.strip():
            first = raw
    if first is None:
        raise CompressedJsonlError(f"JSONL has no non-empty line: {resolve_read_path(path)}")
    return first


def sha256_uncompressed(path: Path) -> str:
    digest = hashlib.sha256()
    with open_binary(path) as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
