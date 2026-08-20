"""Добавление хештегов к тексту поста.

Источник ставит хештеги только в длинный вариант, а в X обычно уходит
короткий — поэтому теги дописываются на нашей стороне, своим набором
для каждой площадки.
"""

import logging
import re

log = logging.getLogger("hashtags")

TAG_RE = re.compile(r"#\w+", re.UNICODE)
# Строка, состоящая только из хештегов.
TAG_LINE_RE = re.compile(r"^\s*(?:#\w+\s*)+$", re.UNICODE)


def _join(text: str, tags: list) -> str:
    """
    Приклеивает теги к тексту. Если текст уже заканчивается строкой хештегов,
    дописываем в неё, чтобы не плодить два блока тегов подряд.
    """
    if not text:
        return " ".join(tags)

    lines = text.split("\n")
    if lines and TAG_LINE_RE.match(lines[-1]):
        lines[-1] = lines[-1].rstrip() + " " + " ".join(tags)
        return "\n".join(lines)

    return f"{text}\n\n{' '.join(tags)}"


def parse(raw: str) -> list:
    """
    Разбирает список тегов из настройки.
    Принимает и '#cs2 #esports', и 'cs2, esports' — решётка проставится сама.
    """
    if not raw:
        return []

    tags = []
    for part in re.split(r"[,\s]+", raw.strip()):
        part = part.strip()
        if not part:
            continue
        if not part.startswith("#"):
            part = "#" + part
        if part not in tags:
            tags.append(part)
    return tags


def append(text: str, raw_tags: str, limit: int = None) -> str:
    """
    Дописывает теги в конец текста.

    Теги, уже присутствующие в тексте, повторно не добавляются (регистр не важен).
    Если задан limit, добавляются только те теги, которые в него влезают —
    иначе короткий пост для X превратился бы в тред из-за хвоста тегов.
    """
    tags = parse(raw_tags)
    if not tags:
        return text

    text = (text or "").rstrip()

    existing = {t.lower() for t in TAG_RE.findall(text)}
    new_tags = [t for t in tags if t.lower() not in existing]
    if not new_tags:
        return text

    if limit is None:
        return _join(text, new_tags)

    # Влезает ли всё целиком.
    candidate = _join(text, new_tags)
    if len(candidate) <= limit:
        return candidate

    # Не влезает — добавляем по одному, пока есть место.
    fitted = []
    for tag in new_tags:
        trial = fitted + [tag]
        if len(_join(text, trial)) > limit:
            break
        fitted = trial

    if not fitted:
        log.warning("Хештеги не влезли в лимит %d, пост уйдёт без них", limit)
        return text

    if len(fitted) < len(new_tags):
        log.info("В лимит %d влезло %d из %d хештегов",
                 limit, len(fitted), len(new_tags))

    return _join(text, fitted)
