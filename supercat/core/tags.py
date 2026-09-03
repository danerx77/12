"""Ochrona i adaptacja tagów (odpowiednik services/TagProtectionService.java)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import List

from .textutil import split_edges


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


# ---------------------------------------------------------------------------
# Dopasowanie znaczników (\\n, \\l, \\p) do oryginału
# ---------------------------------------------------------------------------

#: Kod, który przełamuje wiersz w plikach gier: \\n (spacja w grze), \\l (bez),
#: \\p (nowy akapit). Wielkość liter nie ma znaczenia.
_BREAK_RE = re.compile(r"\\[pPnNlL]")

#: Znak, po którym można bezpiecznie przełamać wiersz (także pełnej
#: szerokości spacja CJK).
_BREAKABLE_AFTER = (" ", "\u3000")

#: Szybkie rozpoznanie tekstu CJK (japoński, chiński, koreański) — po
#: takich znakach wiersz można łamać w dowolnym miejscu, więc minimalna
#: odległość między przełamaniemiami jest mniejsza niż w tekście łacińskim.
_CJK_DETECT_RE = re.compile(
    "[\u3000-\u30ff\u3400-\u9fff\uf900-\ufaff\uff66-\uff9f\uac00-\ud7af]")


def split_code_structure(text: str | None) -> List[List[Tuple[str, str]]]:
    """Rozbija tekst na akapity (``\\p``) i wiersze (``\\n`` / ``\\l``).

    Zwraca listę akapitów; każdy akapit to lista krotek
    ``(treść_wiersza, kod_po_wierszu)`` — kod pustego łańcucha oznacza, że
    wiersz jest ostatni w akapicie. Tekst bez kodów to jeden akapit
    z jednym wierszem.
    """
    if not text:
        return []
    paragraphs: List[List[Tuple[str, str]]] = []
    lines: List[Tuple[str, str]] = []
    last = 0
    for match in _BREAK_RE.finditer(text):
        lines.append((text[last:match.start()], match.group()))
        last = match.end()
        if match.group()[1].lower() == "p":
            paragraphs.append(lines)
            lines = []
    lines.append((text[last:], ""))
    paragraphs.append(lines)
    return paragraphs


def codes_structure_matches(source: str | None, target: str | None) -> bool:
    """Czy tłumaczenie ma TĄ SAMĄ strukturę kodów co oryginał.

    Porównujemy tylko układ (ile akapitów, ile wierszy w akapicie) — nie
    to, który dokładnie znak to przełamał (\\n czy \\l).
    """
    src = split_code_structure(source or "")
    tgt = split_code_structure(target or "")
    if len(src) != len(tgt):
        return False
    for src_par, tgt_par in zip(src, tgt):
        if len(src_par) != len(tgt_par):
            return False
    return True


def _flatten_lines(lines: List[Tuple[str, str]]) -> str:
    """Łączy wiersze w jeden ciąg, wstawiając spację TYLKO w miejscach złącza."""
    parts: List[str] = []
    for text, _code in lines:
        if (parts and text
                and not parts[-1].endswith(_BREAKABLE_AFTER)
                and not text.startswith(_BREAKABLE_AFTER)):
            parts.append(" ")
        parts.append(text)
    return "".join(parts)


def _find_break(text: str, pos: int, window: int) -> Tuple[int, bool]:
    """Miejsce bezpiecznego przełamania w pobliżu ``pos``.

    Zwraca ``(pozycja, czy_zjada_spację)``: przełamanie leży po spacji
    (spacja znika — jej rolę przejmuje kod, jak w oryginale) albo, gdy w
    okolicy nie ma spacji (tekst CJK — można łamać w dowolnym miejscu),
    dokładnie w ``pos``.
    """
    lo = max(0, pos - window)
    hi = min(len(text), pos + window + 1)
    best: Tuple[int, int] | None = None      # (odległość, pozycja)
    i = lo
    while i < hi:
        i = text.find(" ", i)
        if i == -1 or i >= hi:
            break
        dist = abs(i - pos)
        if best is None or dist < best[0]:
            best = (dist, i)
        i += 1
    if best is not None:
        return best[1], True
    return pos, False


def adapt_codes(source: str | None, target: str | None) -> str:
    """Dopasowuje znaczniki ``\\n``/``\\l``/``\\p`` w tłumaczeniu do oryginału.

    W plikach gier linia dialogu ma określoną szerokość, więc tłumaczenie
    powinno przełamywać się w zbliżonych miejscach jak oryginał. Funkcja:

    * nie rusza tłumaczenia, gdy struktura kodów już się zgadza,
    * przenosi akapity (``\\p``) 1:1 — nadwyżkę dokleja do ostatniego,
    * wiersze rozkłada proporcjonalnie do długości wierszy oryginału,
      przełamując przy najbliższej spacji (w CJK — w miejscu proporcji),
    * zachowuje wiodące/końcowe spacje tłumaczenia (wcięcie dialogu).

    Wynik ma te same treść (bez kodów) co wejście, a inną — układ kodów.
    """
    if not source or not target or not target.strip():
        return target or ""
    if codes_structure_matches(source, target):
        return target

    src_paras = split_code_structure(source)
    tgt_paras = split_code_structure(target)
    tgt_flat = [_flatten_lines(par) for par in tgt_paras]

    # Wyrównanie liczby akapitów.
    aligned: List[str]
    if len(tgt_flat) == len(src_paras):
        aligned = tgt_flat
    elif len(tgt_flat) > len(src_paras):
        aligned = list(tgt_flat[:len(src_paras) - 1])
        aligned.append(" ".join(t for t in tgt_flat[len(src_paras) - 1:] if t))
    else:
        # Mniej akapitów niż w oryginale — tekst zostaje w pierwszych
        # akapitach, a brakujących \\p nie wymyślamy (zip pomieta resztę).
        aligned = list(tgt_flat)

    out_paras: List[str] = []
    for src_par, text in zip(src_paras, aligned):
        text = text.strip()
        if not text:
            out_paras.append("")
            continue
        if len(src_par) == 1:
            out_paras.append(text)
            continue

        widths = [len(line) for line, _code in src_par]
        total = sum(widths) or 1
        window = max(2, len(text) // (2 * len(src_par)))
        window = min(window, 12)
        cjk_text = bool(_CJK_DETECT_RE.search(text))
        min_gap = 3 if cjk_text else 4
        tail_min = 2 if cjk_text else 3

        breaks: List[Tuple[int, bool, str]] = []     # (pozycja, zjada spację, kod)
        consumed = 0
        for idx in range(1, len(src_par)):
            wanted = round(len(text) * (consumed + widths[idx - 1]) / total)
            pos, eats = _find_break(text, wanted, window)
            code = src_par[idx - 1][1]
            consumed += widths[idx - 1]
            if breaks:
                last_end = breaks[-1][0] + (1 if breaks[-1][1] else 0)
                if pos - last_end < min_gap:
                    continue        # wiersz byłby zbyt krótki — kod odpada
            if len(text) - (pos + (1 if eats else 0)) < tail_min:
                continue            # po przełamaniu zostałby ułamek wiersza
            breaks.append((pos, eats, code))

        parts: List[str] = []
        start = 0
        for (pos, eats, code) in breaks:
            parts.append(text[start:pos])
            parts.append(code)
            start = pos + 1 if eats else pos
        parts.append(text[start:])
        out_paras.append("".join(parts))

    result = "\\p".join(out_paras)
    lead, _core, trail = split_edges(target)
    return f"{lead}{result}{trail}"
