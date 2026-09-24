"""Normalize only explicit code-wrapped labels and heading enum line breaks."""
import re
from . import reviewer_certificate_annotations as previous
from .construction_assets import require


def project(markdown, categories):
    known = previous.LABELS + ('counterexample category', 'severity', 'captured by mechanical gate')
    labels = '|'.join(map(re.escape, known))
    changes = []
    text = markdown
    pattern = re.compile(r'^([ \t]*(?:(?:[-*]|#{1,6})[ \t]+)?)(?:`|\*\*)(' + labels + r')([：:])(?:`|\*\*)([^\n]*)(\n|$)', re.M)
    def label(match):
        old = match[0]
        new = match[1] + match[2] + match[3] + match[4] + match[5]
        changes.append(dict(original=old, projected=new))
        return new
    text = pattern.sub(label, text)
    # A heading followed by one explicit enum is not an inferred field value.
    pattern = re.compile(r'^([ \t]*(?:#{1,6}[ \t]+)?)(counterexample category|severity)[:：][ \t]*\n[ \t]*`?([a-z_]+)`?[ \t]*(\n|$)', re.M)
    def enum(match):
        allowed = {'hard'} if match[2] == 'severity' else set(categories)
        require(match[3] in allowed, 'unknown explicit enum')
        old = match[0]
        new = match[1] + match[2] + '：' + match[3] + match[4]
        changes.append(dict(original=old, projected=new))
        return new
    text = pattern.sub(enum, text)
    try:
        text, annotations = previous.project(text, categories)
    except ValueError as error:
        if str(error) != 'no supported unambiguous certificate annotation':
            raise
        annotations = None
    require(changes or annotations, 'no supported unambiguous certificate annotation')
    return text, dict(contract='explicit-certificate-label-format-v4', edits=changes,
        annotations=annotations, semantic_content_retained=True, decision_unchanged=True)


def restore(projected, record):
    text = previous.restore(projected, record['annotations']) if record['annotations'] else projected
    for edit in reversed(record['edits']):
        require(text.count(edit['projected']) == 1, 'ambiguous explicit label projection')
        text = text.replace(edit['projected'], edit['original'], 1)
    return text
