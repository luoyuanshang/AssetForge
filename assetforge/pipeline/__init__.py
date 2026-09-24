"""Leak-resistant task-construction primitives."""

__all__ = ["build_abstract_rubric", "validate_abstract_rubric"]


def build_abstract_rubric(*args, **kwargs):
    from .rubric import build_abstract_rubric as implementation

    return implementation(*args, **kwargs)


def validate_abstract_rubric(*args, **kwargs):
    from .rubric import validate_abstract_rubric as implementation

    return implementation(*args, **kwargs)
