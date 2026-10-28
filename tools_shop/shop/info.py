"""
shop/info.py

Сборка информационных и юридических страниц.

Текст разделов хранится простым текстом, поэтому рендерим его сами:

  * пустая строка разделяет абзацы;
  * строки, начинающиеся с «- », собираются в маркированный список;
  * строки, начинающиеся с «1. », «2) » и т.п., — в нумерованный;
  * токены ``[[ИНН]]``, ``[[EMAIL]]`` и другие подставляются из реквизитов
    продавца;
  * блочные токены ``[[РЕКВИЗИТЫ]]`` и ``[[КОНТАКТЫ]]`` должны стоять
    отдельной строкой и вставляют готовый HTML-блок.

Весь пользовательский текст проходит через ``html.escape``: даже если в
админке случайно окажется HTML, он будет показан как текст, а не выполнен.
"""
from __future__ import annotations

import re
from html import escape
from typing import Mapping

from django.template.loader import render_to_string
from django.utils.safestring import mark_safe

#: Блочные токены: работают только отдельной строкой.
BLOCK_TOKENS = {
    "[[РЕКВИЗИТЫ]]": "partials/seller_requisites.html",
    "[[КОНТАКТЫ]]": "partials/seller_contacts.html",
}

TOKEN_RE = re.compile(r"\[\[([A-ZА-ЯЁ_]+)\]\]")
BULLET_RE = re.compile(r"^\s*[-•]\s+(.*)$")
ORDERED_RE = re.compile(r"^\s*\d+[.)]\s+(.*)$")


def _value(seller: Mapping, key: str) -> str:
    return escape(str(seller.get(key) or ""))


def _link(value: str, href_prefix: str) -> str:
    if not value:
        return ""
    return (
        f'<a href="{href_prefix}{escape(value, quote=True)}">'
        f"{escape(value)}</a>"
    )


def seller_tokens(seller: Mapping | None) -> dict[str, str]:
    """Плоский словарь подстановок из реквизитов продавца."""
    seller = seller or {}
    return {
        "НАИМЕНОВАНИЕ": _value(seller, "short_name"),
        "ПОЛНОЕ_НАИМЕНОВАНИЕ": _value(seller, "full_name"),
        "ИНН": _value(seller, "inn"),
        "КПП": _value(seller, "kpp"),
        "ОГРН": _value(seller, "ogrn"),
        "АДРЕС": _value(seller, "legal_address"),
        "EMAIL": _link(str(seller.get("email") or ""), "mailto:"),
        "ТЕЛЕФОН": _link(str(seller.get("phone") or ""), "tel:"),
        "САЙТ": _link(str(seller.get("website") or ""), ""),
    }


def _inline(text: str, tokens: Mapping[str, str]) -> str:
    """Экранирует строку и подставляет строчные токены."""
    return TOKEN_RE.sub(
        lambda match: tokens.get(match.group(1), match.group(0)),
        escape(text),
    )


def _render_blocks(text: str, tokens: Mapping[str, str], seller: Mapping) -> str:
    parts: list[str] = []
    paragraph: list[str] = []
    items: list[str] = []
    list_tag: str | None = None

    def flush_paragraph() -> None:
        if paragraph:
            body = "<br>".join(_inline(line, tokens) for line in paragraph)
            parts.append(f"<p>{body}</p>")
            paragraph.clear()

    def flush_list() -> None:
        nonlocal list_tag
        if items:
            tag = list_tag or "ul"
            parts.append(f"<{tag}>" + "".join(f"<li>{item}</li>" for item in items) + f"</{tag}>")
            items.clear()
        list_tag = None

    def flush_all() -> None:
        flush_paragraph()
        flush_list()

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush_all()
            continue

        if line in BLOCK_TOKENS:
            flush_all()
            parts.append(render_to_string(BLOCK_TOKENS[line], {"seller": seller}))
            continue

        bullet = BULLET_RE.match(line)
        ordered = ORDERED_RE.match(line)
        if bullet or ordered:
            flush_paragraph()
            tag = "ul" if bullet else "ol"
            if list_tag and list_tag != tag:
                flush_list()
            list_tag = tag
            items.append(_inline((bullet or ordered).group(1), tokens))
            continue

        flush_list()
        paragraph.append(line)

    flush_all()
    return "".join(parts)


def render_text(text: str, seller: Mapping | None) -> str:
    """Рендерит текст раздела в безопасный HTML."""
    seller = seller or {}
    return mark_safe(_render_blocks(text or "", seller_tokens(seller), seller))


def render_sections(info, seller: Mapping | None) -> list[dict[str, str]]:
    """Готовит разделы страницы для шаблона: заголовок + безопасный HTML."""
    seller = seller or {}
    tokens = seller_tokens(seller)
    return [
        {
            "heading": section.heading,
            "html": mark_safe(_render_blocks(section.body or "", tokens, seller)),
        }
        for section in info.sections.all()
    ]
