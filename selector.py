"""Разбор манифеста и выбор содержимого поста.

Формат источника:

    [картинки]  01-picks.png, 02-analysis.png       (отдельными сообщениями)
    [манифест]  threads · scoreboard · Team Spirit vs Luminosity Gaming
                01-picks.png · https://t.me/c/4346691060/11
                02-analysis.png · https://t.me/c/4346691060/12
    [текст]     🤖 10 AI models pick ... 🎮 Link in bio

Манифест служит разделителем: он говорит, какие файлы относятся к посту,
и одновременно закрывает предыдущий пост. Картинки берутся по ссылкам
из манифеста — это надёжнее, чем угадывать по времени поступления.
"""

import logging
import re

import post_filter
from config import MANIFEST_TYPES, SELECT_STRATEGY

log = logging.getLogger("selector")

# threads · <тип> · <матч>   либо   threads · <матч>
MANIFEST_RE = re.compile(r"^\s*threads\s*[·:\-]\s*(.+)$", re.IGNORECASE)
FILENAME_RE = re.compile(r"([\w\-. ]+\.(?:png|jpe?g|webp|gif|mp4|mov))", re.IGNORECASE)
TME_LINK_RE = re.compile(r"https?://t\.me/c/(\d+)/(\d+)")

_WANTED_TYPES = [t.strip().lower() for t in MANIFEST_TYPES.split(",") if t.strip()]


def is_manifest(text: str) -> bool:
    """Манифест — служебное сообщение со списком файлов для Threads."""
    if not text:
        return False
    return bool(MANIFEST_RE.match(text) and FILENAME_RE.search(text))


def parse_manifest(text: str) -> dict:
    """
    Разбирает шапку манифеста.

    'threads · scoreboard · Team Spirit vs Luminosity'
        -> {'type': 'scoreboard', 'title': 'Team Spirit vs Luminosity'}
    'threads · Team Spirit vs Luminosity'
        -> {'type': '', 'title': 'Team Spirit vs Luminosity'}
    """
    if not text:
        return {"type": "", "title": "", "links": [], "filenames": []}

    head = text.splitlines()[0]
    m = MANIFEST_RE.match(head)
    rest = m.group(1).strip() if m else ""

    parts = [p.strip() for p in re.split(r"\s*[·|]\s*", rest) if p.strip()]
    if len(parts) >= 2:
        kind, title = parts[0].lower(), " · ".join(parts[1:])
    else:
        kind, title = "", (parts[0] if parts else "")

    return {
        "type": kind,
        "title": title,
        "links": TME_LINK_RE.findall(text),
        "filenames": [n.strip().lower() for n in FILENAME_RE.findall(text)],
    }


def type_allowed(manifest_type: str) -> bool:
    """Фильтр по типу манифеста. Пустой список = разрешены все типы."""
    if not _WANTED_TYPES:
        return True
    return (manifest_type or "").lower() in _WANTED_TYPES


def _media_by_filenames(filenames: list, media: list) -> list:
    """Оставляет вложения, перечисленные в манифесте, в его порядке."""
    by_name = {}
    for m in media:
        name = (m.get("filename") or "").strip().lower()
        if name:
            by_name.setdefault(name, m)
    return [by_name[n] for n in filenames if n in by_name]


def _all_media(candidates: list) -> list:
    media, seen = [], set()
    for c in candidates:
        for m in c.get("media", []):
            if m["key"] not in seen:
                seen.add(m["key"])
                media.append(m)
    return media


def choose(burst_manifest: str, candidates: list) -> dict:
    """
    Возвращает {'text', 'media', 'manifest_links', 'message_id'}
    либо {} если публиковать нечего.
    """
    manifest = parse_manifest(burst_manifest) if burst_manifest else {
        "type": "", "title": "", "links": [], "filenames": []
    }

    if burst_manifest and not type_allowed(manifest["type"]):
        log.info("Тип манифеста %r не в списке разрешённых — пропускаю",
                 manifest["type"])
        return {}

    text_candidates = [
        c for c in candidates
        if c.get("text") and post_filter.matches(c["text"])
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
    if manifest["filenames"]:
        picked = _media_by_filenames(manifest["filenames"], media)
        if picked:
            media = picked

    if len(text_candidates) > 1:
        log.info("Вариантов текста: %d, выбран msg %s (%d симв.) по стратегии %s",
                 len(text_candidates), chosen.get("message_id"),
                 len(chosen.get("text", "")), SELECT_STRATEGY)

    return {
        "message_id": chosen.get("message_id"),
        "text": chosen.get("text", ""),
        "media": media,
        "manifest_links": manifest["links"],
        "manifest_type": manifest["type"],
        "manifest_title": manifest["title"],
    }
