import re

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

from ..search import tokens

register = template.Library()


def _token_pattern(token: str) -> str:
    # «е» в запросе подсвечивает и «ё», «.» — и десятичную запятую
    special = {"е": "[её]", ".": "[.,]"}
    return "".join(special.get(ch) or re.escape(ch) for ch in token)


@register.filter
def highlight(text, query):
    """Экранирует текст и оборачивает совпадения со словами запроса в <mark>."""
    text = "" if text is None else str(text)
    words = sorted(tokens(query or ""), key=len, reverse=True)
    if not words:
        return escape(text)
    pattern = re.compile("|".join(_token_pattern(w) for w in words), re.IGNORECASE)
    parts, pos = [], 0
    for match in pattern.finditer(text):
        parts.append(escape(text[pos:match.start()]))
        parts.append(f"<mark>{escape(match.group(0))}</mark>")
        pos = match.end()
    parts.append(escape(text[pos:]))
    # безопасно: каждый фрагмент текста выше прошёл через escape()
    return mark_safe("".join(parts))  # noqa: S308
