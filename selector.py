"""Выбор текста и картинок из пачки сообщений.

Источник присылает один материал россыпью:
  - картинки отдельными сообщениями (01-picks.png, 02-analysis.png)
  - манифест вида "threads · Матч / 01-picks.png · ссылка / 02-analysis.png · ссылка"
  - несколько текстовых вариантов (instagram, x, длинный) — все с фразой-маркером

В Threads должен уйти один пост: один текст + все относящиеся к нему картинки.
"""

import logging
import re

import post_filter
from config import SELECT_STRATEGY

log = logging.getLogger("selector")

# Манифест: строка, начинающаяся со слова threads, где перечислены файлы.
MANIFEST_RE = re.compile(r"^\s*threads\s*[·:\-]", re.IGNORECASE)
FILENAME_RE = re.compile(r"([\w\-. ]+\.(?:png|jpe?g|webp|gif|mp4|mov))", re.IGNORECASE)


def _find_manifest(candidates: list) -> str:
    for c in candidates:
        text = c.get("text", "")
        if text and MANIFEST_RE.match(text) and FILENAME_RE.search(text):
            return text
    return ""


def _all_media(candidates: list) -> list:
    """Все вложения пачки в порядке поступления, без повторов."""
    media, seen = [], set()
    for c in candidates:
        for m in c.get("media", []):
            if m["key"] not in seen:
                seen.add(m["key"])
                media.append(m)
    return media


def _media_by_manifest(manifest: str, media: list) -> list:
    """
    Оставляет только файлы, перечисленные в манифесте, и в том же порядке.
    Если ничего не совпало — возвращает пустой список, решение примет вызывающий.
    """
    wanted = [n.strip().lower() for n in FILENAME_RE.findall(manifest)]
    by_name = {}
    for m in media:
        name = (m.get("filename") or "").strip().lower()
        if name:
            by_name.setdefault(name, m)

    ordered = [by_name[n] for n in wanted if n in by_name]
    return ordered


def choose(candidates: list) -> dict:
    """
    Возвращает {'text', 'media', 'message_id'} либо {} если публиковать нечего.

    Текст берётся из вариантов, прошедших фильтр:
      longest — самый информативный (по умолчанию)
      first   — первый пришедший
      last    — последний пришедший

    Картинки собираются со всей пачки; если есть манифест, он задаёт
    состав и порядок.
    """
    if not candidates:
        return {}

    manifest = _find_manifest(candidates)

    # Текстовые варианты: манифест и подписи к картинкам сюда не попадают,
    # потому что не содержат фразу-маркер.
    text_candidates = [
        c for c in candidates
        if c.get("text") and post_filter.matches(c["text"]) and c["text"] != manifest
    ]

    if not text_candidates:
        return {}

    if SELECT_STRATEGY == "first":
        chosen = text_candidates[0]
    elif SELECT_STRATEGY == "last":
        chosen = text_candidates[-1]
    else:
        chosen = max(text_candidates, key=lambda c: len(c.get("text", "")))

    media = _all_media(candidates)

    if manifest:
        picked = _media_by_manifest(manifest, media)
        if picked:
            log.info("Манифест задал %d файл(ов) из %d доступных",
                     len(picked), len(media))
            media = picked
        else:
            log.warning("Манифест найден, но файлы не сопоставились — беру все")

    if len(candidates) > 1:
        log.info(
            "Пачка: %d сообщений, %d текстовых вариантов, %d медиа."
            " Выбран msg %s (%d симв.) по стратегии %s",
            len(candidates), len(text_candidates), len(media),
            chosen.get("message_id"), len(chosen.get("text", "")), SELECT_STRATEGY,
        )

    return {
        "message_id": chosen.get("message_id"),
        "text": chosen.get("text", ""),
        "media": media,
    }
