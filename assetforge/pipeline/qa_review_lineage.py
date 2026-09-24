"""Bind Reviewer requirements to the exact immutable Author prompt, fail closed."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path


@lru_cache(maxsize=8192)
def _read_author(path, mtime_ns, size):
    raw = Path(path).read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def validate_author_rubric(author_receipt, rubric, *, expected_author_sha256=None):
    author_receipt, rubric = Path(author_receipt), Path(rubric)
    stat = author_receipt.stat()
    author, author_sha = _read_author(str(author_receipt.resolve()), stat.st_mtime_ns, stat.st_size)
    if expected_author_sha256 and expected_author_sha256 != author_sha:
        raise ValueError('Author receipt hash drift')
    original = author.get('source_rubric', {}).get('content_sha256')
    configured = author.get('config', {}).get('rubric_sha256')
    supplied = hashlib.sha256(rubric.read_bytes()).hexdigest()
    if not original or not configured or original != configured or original != supplied:
        raise ValueError('Reviewer Rubric differs from original Author Rubric; do not judge or call provider')
    return supplied


def valid_review_rubric_binding(audit, root):
    try:
        binding = audit['packet']['source_binding']
        author = binding['execution_evidence']['author_receipt']
        rubric = binding['rubric']
        root = Path(root).resolve()
        author_path, rubric_path = (root/author['path']).resolve(), (root/rubric['path']).resolve()
        author_path.relative_to(root); rubric_path.relative_to(root)
        digest = validate_author_rubric(author_path, rubric_path, expected_author_sha256=author['sha256'])
        return digest == rubric['sha256']
    except (OSError, KeyError, ValueError, TypeError):
        return False
