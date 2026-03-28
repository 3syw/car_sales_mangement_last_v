import re

from django.utils.html import strip_tags


_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")


def sanitize_plain_text(value, *, max_length=0):
    """Sanitize user-provided plain text while preserving normal business input."""
    if value is None:
        return ''

    cleaned = strip_tags(str(value))
    cleaned = _CONTROL_CHARS_RE.sub('', cleaned).strip()
    if max_length and len(cleaned) > max_length:
        cleaned = cleaned[:max_length]
    return cleaned
