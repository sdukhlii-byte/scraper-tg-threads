"""Выбор одного варианта из пачки.

Источник публикует один и тот же материал несколькими вариантами подряд
(короткий для instagram, короткий для x, длинный с разбором и хештегами).
В Threads должен уйти только один.
"""

import logging

from config import SELECT_STRATEGY

log = logging.getLogger("selector")


def choose(candidates: list) -> dict:
    """
    Возвращает выбранный вариант.

    longest — самый информативный (по умолчанию)
    first   — первый пришедший
    last    — последний пришедший
    """
    if not candidates:
        return {}

    with_media = [c for c in candidates if c.get("media")]

    if SELECT_STRATEGY == "first":
        chosen = candidates[0]
    elif SELECT_STRATEGY == "last":
        chosen = candidates[-1]
    else:
        chosen = max(candidates, key=lambda c: len(c.get("text", "")))

    # Если в выбранном варианте медиа нет, а в пачке оно было — подтягиваем,
    # иначе картинки из соседнего варианта просто пропадут.
    if not chosen.get("media") and with_media:
        chosen = {**chosen, "media": with_media[0]["media"]}

    if len(candidates) > 1:
        log.info(
            "Пачка из %d вариантов, выбран msg %s (%d симв.) по стратегии %s",
            len(candidates), chosen.get("message_id"),
            len(chosen.get("text", "")), SELECT_STRATEGY,
        )

    return chosen
