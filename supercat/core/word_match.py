"""Dopasowanie słów + TM — osobna ścieżka od dopasowania zdań.

Zdanie źródłowe „MISTY” ma dostać hasło z pamięci („MISTY”), a nie cały
opis sali tylko dlatego, że to słowo tam występuje. W dłuższym segmencie
hasła z TM podmieniamy w miejscu, jak w glosariuszu.
"""
from __future__ import annotations


def is_word_span(flat: str, start: int, length: int) -> bool:
    """Czy trafienie w spłaszczonym tekście stoi na granicy słowa."""
    if start < 0 or length <= 0 or start + length > len(flat):
        return False
    if start > 0 and flat[start - 1].isalnum():
        return False
    end = start + length
    if end < len(flat) and flat[end].isalnum():
        return False
    return True


def candidate_too_long(seg_word_count: int, cand_word_count: int) -> bool:
    """Akapit z TM nie jest tłumaczeniem krótkiego hasła (MISTY ⊂ bio sali)."""
    if seg_word_count <= 0:
        return cand_word_count > 0
    return cand_word_count > max(seg_word_count * 2 + 1, 3)
