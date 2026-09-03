"""Ochrona i adaptacja tagów (odpowiednik services/TagProtectionService.java)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import List


class TagType(str, Enum):
    VARIABLE = "VARIABLE"
    NEWLINE = "NEWLINE"
    END = "END"
    HTML = "HTML"
    BRACKET = "BRACKET"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class TagInfo:
    text: str
    start: int
    type: TagType


TAG_PATTERNS = [
    re.compile(r"\{([A-Za-z_0-9]+)\}"),
    re.compile(r"\\[pPnNlL]"),
    re.compile(r"<<KON>>"),
    re.compile(r"<[^>]+>"),
    re.compile(r"\[[^\]]+\]"),
]


def _tag_type(tag: str) -> TagType:
    if tag.startswith("{") and tag.endswith("}"):
        return TagType.VARIABLE
    if tag.startswith("\\") and len(tag) == 2:
        return TagType.NEWLINE
    if tag == "<<KON>>":
        return TagType.END
    if tag.startswith("<") and tag.endswith(">"):
        return TagType.HTML
    if tag.startswith("[") and tag.endswith("]"):
        return TagType.BRACKET
    return TagType.UNKNOWN


def extract_tags(text: str | None) -> List[TagInfo]:
    """Zwraca listę tagów w kolejności wystąpienia."""
    tags: List[TagInfo] = []
    if not text:
        return tags
    for pattern in TAG_PATTERNS:
        for match in pattern.finditer(text):
            tags.append(TagInfo(match.group(), match.start(), _tag_type(match.group())))
    tags.sort(key=lambda t: t.start)
    return tags


def count_tags(text: str | None) -> int:
    return len(extract_tags(text))


def remove_tags(text: str | None) -> str:
    if not text:
        return ""
    result = text
    for pattern in TAG_PATTERNS:
        result = pattern.sub("", result)
    return result.strip()


def _group_tags(tags: List[TagInfo]) -> List[List[TagInfo]]:
    """Grupuje tagi sąsiadujące ze sobą (bez odstępu)."""
    groups: List[List[TagInfo]] = []
    if not tags:
        return groups
    current = [tags[0]]
    for prev, curr in zip(tags, tags[1:]):
        if prev.start + len(prev.text) == curr.start:
            current.append(curr)
        else:
            groups.append(current)
            current = [curr]
    groups.append(current)
    return groups


def adapt_translation(source_text: str | None, tm_translation: str | None) -> str:
    """Dopasowuje tagi z bieżącego segmentu źródłowego do tłumaczenia z TM.

    Tagi w tłumaczeniu z pamięci są zastępowane tagami z aktualnego źródła
    (typ po typie, grupa po grupie), dzięki czemu podpowiedź TM pasuje do
    aktualnego segmentu nawet gdy numery zmiennych są inne.
    """
    if source_text is None or tm_translation is None:
        return tm_translation or ""

    source_tags = extract_tags(source_text)
    tm_tags = extract_tags(tm_translation)
    if not source_tags and not tm_tags:
        return tm_translation

    replacements: List[tuple[int, int, str]] = []
    for tag_type in TagType:
        s_groups = _group_tags([t for t in source_tags if t.type == tag_type])
        t_groups = _group_tags([t for t in tm_tags if t.type == tag_type])
        for idx, t_group in enumerate(t_groups):
            start = t_group[0].start
            end = t_group[-1].start + len(t_group[-1].text)
            replacement = "".join(t.text for t in s_groups[idx]) if idx < len(s_groups) else ""
            replacements.append((start, end, replacement))

    # zamiany od końca, aby nie przesuwać indeksów
    replacements.sort(key=lambda r: r[0], reverse=True)
    result = tm_translation
    for start, end, replacement in replacements:
        result = result[:start] + replacement + result[end:]
    return result.strip()


def normalize_tags_for_comparison(text: str | None) -> str:
    """Normalizuje tagi do jednego znaku – dla porównań fuzzy."""
    if not text:
        return ""
    result = text
    result = re.sub(r"\{([A-Za-z_0-9]+)\}", "@", result)
    result = re.sub(r"\\[pPnNlL]", "~", result)
    result = result.replace("<<KON>>", "^")
    result = re.sub(r"<[^>]+>", "<", result)
    result = re.sub(r"\[[^\]]+\]", "[", result)
    return result
