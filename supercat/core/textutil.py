"""Narzędzia tekstowe wspólne dla wyszukiwania i zachowywania białych znaków.

Dwa zadania:

1. **Wyszukiwanie odporne na znaczniki** – w plikach gier tekst bywa przełamany
   znacznikiem (``STAMP CARD\\nSystem``), więc zwykłe „zawiera” nie znajdzie
   frazy „STAMP CARD System”. Funkcje tutaj normalizują tekst (znaczniki →
   spacja, opcjonalnie bez ogonków) i PAMIĘTAJĄ, gdzie w oryginale leży każdy
   znak, dzięki czemu dopasowania można podświetlić w oryginalnym tekście.

2. **Białe znaki na brzegach segmentu** – plik źródłowy często zaczyna wiersz
   spacją (wcięcie dialogu). Segment musi ją zachować, a tłumaczenie powinno ją
   odziedziczyć.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

# Znaczniki spotykane w plikach gier i CAT: \n \p \l, <<KON>>, twarde końce wiersza.
CODE_PATTERN = re.compile(r"\\[a-zA-Z]|<<[^<>]{1,24}>>|\r\n|[\r\n\t]")

#: Litery z diakrytyką → odpowiednik bez ogonka (1:1, żeby zachować pozycje).
_FOLD_MAP = str.maketrans(
    "ąćęłńóśźżĄĆĘŁŃÓŚŹŻáàâäãåéèêëíìîïóòôöõúùûüýÿñçÁÀÂÄÃÅÉÈÊËÍÌÎÏÓÒÔÖÕÚÙÛÜÝÑÇ",
    "acelnoszzACELNOSZZaaaaaaeeeeiiiiooooouuuuyyncAAAAAAEEEEIIIIOOOOOUUUUYNC",
)


def fold_accents(text: str) -> str:
    """Usuwa polskie i zachodnie diakrytyki, zachowując długość napisu."""
    return (text or "").translate(_FOLD_MAP)


# ----------------------------------------------------------- białe znaki
def fix_doubled_break_codes(text: str | None) -> str:
    """Poprawia podwójne backslashy przed znakami kodów: ``\\n`` → ``\n``.

    Niektóre ekstraktyory uciekają backslashy, więc kod przełamania ląduje
    w pliku z podwójnym backslashem. Parzysta liczba backslashów przed
    literą kurczy się do jednego; nieparzysta zostaje (nie ruszamy czegoś,
    czego nie rozumiemy).
    """
    if not text or "\\" not in text:
        return text or ""

    def _fix(m: "re.Match") -> str:
        bs = m.group(0)
        return "\\" if len(bs) % 2 == 0 else bs

    return _DOUBLE_BS_RE.sub(_fix, text)


_DOUBLE_BS_RE = re.compile(r"\\+(?=[A-Za-z])")


def split_edges(text: str) -> Tuple[str, str, str]:
    """Rozdziela tekst na (wiodące białe znaki, treść, końcowe białe znaki)."""
    if not text:
        return "", "", ""
    stripped = text.strip()
    if not stripped:
        return text, "", ""
    start = text.index(stripped[0])
    # index() znajduje pierwszy znak treści – dla pewności liczymy od lewej
    start = len(text) - len(text.lstrip())
    end = len(text.rstrip())
    return text[:start], text[start:end], text[end:]


def copy_edge_whitespace(source: str, target: str) -> str:
    """Nadaje tłumaczeniu takie same spacje na brzegach, jakie ma źródło.

    Silniki MT i pamięć TM zwracają tekst przycięty, a w pliku gry wiodąca
    spacja bywa istotna (wcięcie wiersza dialogu).
    """
    if not target or not target.strip():
        return target
    lead, _core, trail = split_edges(source or "")
    _tl, tcore, _tt = split_edges(target)
    return f"{lead}{tcore}{trail}"


def describe_edges(text: str) -> str:
    """Krótki opis białych znaków na brzegach, np. „␣2 z przodu”. Pusty, gdy brak."""
    lead, _core, trail = split_edges(text or "")
    parts = []
    if lead:
        parts.append(f"␣{len(lead)} z przodu")
    if trail:
        parts.append(f"␣{len(trail)} na końcu")
    return ", ".join(parts)


#: Znak zastępujący spację na brzegu segmentu w widoku tabeli.
#: „·” (kropka środkowa) jest ledwo widoczna przy małej czcionce, dlatego
#: domyślnie używamy „␣” (otwarte pole, U+2423) – standardowego symbolu spacji.
SPACE_MARKER = "␣"
TAB_MARKER = "→"
NEWLINE_MARKER = "⏎"

#: Zestawy znaków do wyboru w Ustawieniach (nazwa → (spacja, tabulator, koniec wiersza)).
MARKER_STYLES = {
    "␣ → ⏎  (standardowe)": ("␣", "→", "⏎"),
    "· » ¶  (dyskretne)": ("·", "»", "¶"),
    "▁ ▸ ↵  (wyraziste)": ("▁", "▸", "↵"),
    "_ > \\n  (tylko ASCII)": ("_", ">", "\\n"),
}
DEFAULT_MARKER_STYLE = "␣ → ⏎  (standardowe)"


def markers_for_style(style: str) -> Tuple[str, str, str]:
    """Zwraca (spacja, tabulator, koniec wiersza) dla nazwy zestawu."""
    return MARKER_STYLES.get(style, MARKER_STYLES[DEFAULT_MARKER_STYLE])


def mark_edges(text: str, marker: str = SPACE_MARKER, tab_marker: str = TAB_MARKER) -> str:
    """Zamienia białe znaki na BRZEGACH na widoczny znak (do podglądu w tabeli)."""
    if not text:
        return text

    def _visible(chunk: str) -> str:
        return "".join(tab_marker if ch == "\t" else marker for ch in chunk)

    lead, core, trail = split_edges(text)
    if not core:
        return _visible(text)
    return _visible(lead) + core + _visible(trail)


def display_text(text: str, show_spaces: bool = True, show_newlines: bool = True,
                 space_marker: str = SPACE_MARKER, tab_marker: str = TAB_MARKER,
                 newline_marker: str = NEWLINE_MARKER) -> str:
    """Przygotowuje tekst do pokazania w tabeli / na liście wyników.

    Obie zamiany są NIEZALEŻNE i sterowane z Ustawień:

    * ``show_spaces`` – spacje i tabulatory na brzegach jako ``␣`` / ``→``,
    * ``show_newlines`` – twarde końce wiersza jako ``⏎``.

    Gdy oba są wyłączone, tekst wraca w postaci surowej (końce wiersza zamienia
    się wtedy na zwykłą spację, bo w jednym wierszu tabeli i tak się nie zmieszczą).
    """
    if not text:
        return text
    out = mark_edges(text, space_marker, tab_marker) if show_spaces else text
    if show_newlines:
        return out.replace("\r\n", f" {newline_marker} ").replace("\n", f" {newline_marker} ")
    return out.replace("\r\n", " ").replace("\n", " ")


# ------------------------------------------------------------ szukanie
def normalize_for_search(
    text: str,
    ignore_codes: bool = False,
    ignore_accents: bool = False,
    case_sensitive: bool = False,
) -> str:
    """Uproszczona postać tekstu do porównań (bez mapy pozycji).

    Znaczniki zamieniane są na spację, wielokrotne spacje sklejane.
    """
    text = text or ""
    if ignore_codes:
        text = CODE_PATTERN.sub(" ", text)
        text = re.sub(r"\s+", " ", text)
    if ignore_accents:
        text = fold_accents(text)
    if not case_sensitive:
        text = text.lower()
    return text


#: Znacznik w tekście: literalne \n, <<KON>>, twardy koniec wiersza, tabulator.
_CODE_ALT = r"\\[a-zA-Z]|<<[^<>]{1,24}>>|\r\n|[\r\n\t]"
#: Separator: dowolna mieszanka spacji i znaczników (co najmniej jeden znak).
_SEP_PATTERN = rf"(?:\s|{_CODE_ALT})+"
#: Znacznik, który może stać W ŚRODKU wyrazu (``CARD\nSystem``) – opcjonalny.
_CODE_OPT = rf"(?:{_CODE_ALT})*"

#: Litera bez ogonka → klasa znaków obejmująca warianty z ogonkiem.
_ACCENT_VARIANTS: dict = {}
for _plain, _fancy in (
    ("a", "ąáàâäã"), ("c", "ćç"), ("e", "ęéèêë"), ("l", "ł"), ("n", "ńñ"),
    ("o", "óòôöõ"), ("s", "ś"), ("z", "źż"), ("i", "íìîï"), ("u", "úùûü"),
    ("y", "ýÿ"),
):
    _ACCENT_VARIANTS[_plain] = _plain + _fancy


def _char_pattern(ch: str, ignore_accents: bool) -> str:
    if ignore_accents:
        variants = _ACCENT_VARIANTS.get(ch.lower())
        if variants:
            chars = variants + variants.upper()
            return "[" + re.escape(chars) + "]"
    return re.escape(ch)


def _tokens_of(needle: str, ignore_codes: bool) -> List[str]:
    """Dzieli szukaną frazę na „słowa” – separatorem jest spacja lub znacznik."""
    if ignore_codes:
        cleaned = CODE_PATTERN.sub(" ", needle)
    else:
        cleaned = needle
    return [t for t in re.split(r"\s+", cleaned) if t]


def build_search_regex(needle: str, mode: str = "contains", case_sensitive: bool = False,
                       ignore_accents: bool = False, ignore_codes: bool = False):
    """Buduje wyrażenie regularne dopasowujące frazę wprost w ORYGINALNYM tekście.

    Dzięki temu pozycje trafień są od razu poprawne (bez mapy indeksów), a całą
    pracę wykonuje silnik regex w C – wyszukiwanie w dużym projekcie jest
    kilkadziesiąt razy szybsze niż przechodzenie tekstu znak po znaku.
    """
    flags = re.UNICODE | (0 if case_sensitive else re.IGNORECASE)
    if mode == "regex":
        return re.compile(needle, flags)

    tokens = _tokens_of(needle, ignore_codes)
    if not tokens:
        return None

    parts = []
    for token in tokens:
        chars = [_char_pattern(ch, ignore_accents) for ch in token]
        glue = _CODE_OPT if ignore_codes else ""
        parts.append(glue.join(chars))
    sep = _SEP_PATTERN if ignore_codes else re.escape(" ")
    body = sep.join(parts)
    if mode == "word":
        body = rf"(?<!\w){body}(?!\w)"
    return re.compile(body, flags)


def _regex_for(needle: str, mode: str, case_sensitive: bool,
               ignore_accents: bool, ignore_codes: bool):
    key = (needle, mode, case_sensitive, ignore_accents, ignore_codes)
    cached = _REGEX_CACHE.get(key)
    if cached is None:
        cached = build_search_regex(needle, mode, case_sensitive, ignore_accents, ignore_codes)
        if len(_REGEX_CACHE) > 64:
            _REGEX_CACHE.clear()
        _REGEX_CACHE[key] = cached
    return cached


_REGEX_CACHE: dict = {}


def find_matches(
    text: str,
    needle: str,
    mode: str = "contains",
    case_sensitive: bool = False,
    ignore_accents: bool = False,
    ignore_codes: bool = False,
    limit: int = 500,
) -> List[Tuple[int, int]]:
    """Znajduje wystąpienia frazy i zwraca zakresy (start, koniec) w ORYGINALE.

    Tryby: ``contains`` | ``word`` (całe słowo) | ``exact`` | ``regex``.
    Przy ``ignore_codes`` znaczniki (\\n, \\p, <<KON>>, twarde końce wiersza)
    liczą się jak spacja – fraza "STAMP CARD System" znajdzie
    "STAMP CARD\\nSystem".
    """
    if not text or not needle:
        return []

    if mode == "exact":
        left = normalize_for_search(text, ignore_codes, ignore_accents, case_sensitive).strip()
        right = normalize_for_search(needle, ignore_codes, ignore_accents, case_sensitive).strip()
        if left and left == right:
            lead = len(text) - len(text.lstrip())
            return [(lead, len(text.rstrip()))]
        return []

    pattern = _regex_for(needle, mode, case_sensitive, ignore_accents, ignore_codes)
    if pattern is None:
        return []

    spans: List[Tuple[int, int]] = []
    for m in pattern.finditer(text):
        if m.end() > m.start():
            spans.append((m.start(), m.end()))
        if len(spans) >= limit:
            break
    return spans


def count_matches(text: str, needle: str, **kwargs) -> int:
    return len(find_matches(text, needle, **kwargs))


def context_snippet(text: str, span: Tuple[int, int], width: int = 40,
                    newline_marker: Optional[str] = NEWLINE_MARKER) -> str:
    """Fragment tekstu wokół dopasowania, ze znacznikami «…».

    ``newline_marker=None`` wyłącza oznaczanie końców wiersza (zamienia je
    na zwykłą spację) – sterowane ustawieniem „Pokazuj znaki końca wiersza”.
    """
    if not text:
        return ""
    s, e = span
    left = max(0, s - width)
    right = min(len(text), e + width)
    prefix = "…" if left > 0 else ""
    suffix = "…" if right < len(text) else ""
    out = f"{prefix}{text[left:s]}«{text[s:e]}»{text[e:right]}{suffix}"
    replacement = f" {newline_marker} " if newline_marker else " "
    return out.replace("\r\n", replacement).replace("\n", replacement)


def replace_matches(text: str, needle: str, replacement: str, mode: str = "contains",
                    case_sensitive: bool = False, ignore_accents: bool = False,
                    ignore_codes: bool = False) -> Tuple[str, int]:
    """Zamienia wszystkie wystąpienia; zwraca (nowy tekst, liczba zamian)."""
    spans = find_matches(text, needle, mode, case_sensitive, ignore_accents, ignore_codes,
                         limit=10 ** 6)
    if not spans:
        return text, 0
    out = []
    last = 0
    for s, e in spans:
        if s < last:      # nakładające się dopasowania – pomijamy
            continue
        out.append(text[last:s])
        out.append(replacement)
        last = e
    out.append(text[last:])
    return "".join(out), len(spans)
