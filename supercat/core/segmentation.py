"""Segmentacja tekstu (odpowiednik services/SegmentationService.java)."""
from __future__ import annotations

import re
from typing import List, Optional

from .project import SegmentationSettings

# Skróty, po których NIE kończymy zdania.
ABBREVIATIONS = {
    "np", "itp", "itd", "tzn", "tzw", "dr", "prof", "inż", "mgr", "ul", "godz",
    "r", "m.in", "ok", "por", "zob", "str", "tj", "pkt", "nr", "art",
    "mr", "mrs", "ms", "dr", "prof", "inc", "ltd", "etc", "e.g", "i.e", "vs", "fig", "no",
}


def segment_text(text: str, settings: SegmentationSettings) -> List[str]:
    """Dzieli tekst na segmenty zgodnie z ustawieniami projektu.

    Gdy ``settings.preserve_whitespace`` jest włączone (domyślnie), spacje
    i tabulatory na początku oraz końcu segmentu NIE są obcinane. W plikach gier
    wiodąca spacja to często wcięcie wiersza dialogu i jej utrata zmienia wygląd
    tekstu w grze.
    """
    if not text:
        return []
    if not settings.enabled:
        return [text]

    mode = (settings.mode or "sentence").lower()
    if mode == "line":
        segments = _by_line(text)
    elif mode == "paragraph":
        segments = _by_paragraph(text)
    elif mode == "custom_delimiter":
        segments = _by_custom_delimiter(text, settings.custom_delimiter)
    elif mode == "regex":
        segments = _by_regex(text, settings.regex_pattern)
    else:
        segments = _by_sentence(
            text, settings.delimiters,
            getattr(settings, "preserve_whitespace", True),
            parse_abbreviations(getattr(settings, "custom_abbreviations", "")),
            getattr(settings, "require_uppercase_after", False),
            getattr(settings, "skip_after_numbers", False),
        )

    if getattr(settings, "split_on_codes", False):
        segments = _split_on_codes(segments)
    segments = _merge_short(segments, getattr(settings, "min_segment_length", 0))

    if getattr(settings, "preserve_whitespace", True):
        # zachowujemy oryginalne wcięcia, usuwamy tylko znaki końca wiersza
        return [s.strip("\r\n") for s in segments if s and s.strip()]
    return [s.strip() for s in segments if s and s.strip()]


def _by_line(text: str) -> List[str]:
    return [line for line in re.split(r"\r?\n", text) if line.strip()]


def _by_paragraph(text: str) -> List[str]:
    return [p for p in re.split(r"\r?\n\s*\r?\n", text) if p.strip()]


def _by_custom_delimiter(text: str, delimiter: str) -> List[str]:
    if not delimiter:
        return [text]
    return [p for p in text.split(delimiter) if p.strip()]


def _by_regex(text: str, pattern: str) -> List[str]:
    if not pattern:
        return [text]
    try:
        return [p for p in re.split(pattern, text) if p and p.strip()]
    except re.error:
        return [text]


def parse_abbreviations(raw: str) -> set:
    """Zamienia listę skrótów z Ustawień („np., itd., dr”) na zbiór."""
    if not raw:
        return set()
    out = set()
    for part in re.split(r"[,;\n]", raw):
        word = part.strip().rstrip(".").lower()
        if word:
            out.add(word)
    return out


#: Wiersze techniczne w potrójnych nawiasach: <<< FILE: ... >>>, <<KON>>.
#: Nie wolno ich dzielić w środku – dwukropek w „FILE:” rozbijał je na dwa
#: segmenty, przez co reguły wykluczania przestawały pasować.
_PROTECTED_BLOCK_RE = re.compile(r"<<<.*?>>>|<<[^<>]{1,24}>>")


def _protected_spans(text: str) -> List[tuple]:
    return [(m.start(), m.end()) for m in _PROTECTED_BLOCK_RE.finditer(text)]


def _inside_protected(position: int, spans: List[tuple]) -> bool:
    return any(start <= position < end for start, end in spans)


def _by_sentence(text: str, delimiters: str, preserve_whitespace: bool = True,
                 extra_abbreviations: Optional[set] = None,
                 require_uppercase: bool = False,
                 skip_after_numbers: bool = False) -> List[str]:
    """Podział na zdania z uwzględnieniem skrótów i liczb dziesiętnych."""
    delims = delimiters or ".!?"
    escaped = re.escape(delims)
    segments: List[str] = []

    for paragraph in re.split(r"\r?\n\s*\r?\n", text):
        if not paragraph.strip():
            continue
        buffer = ""
        i = 0
        protected = _protected_spans(paragraph)
        while i < len(paragraph):
            ch = paragraph[i]
            buffer += ch
            if protected and _inside_protected(i, protected):
                # Wnętrze <<< … >>> zostaje w całości, ale zamknięcie bloku
                # kończy segment – inaczej nagłówek skleiłby się ze zdaniem
                # w następnym wierszu i reguła wykluczania by go nie objęła.
                ends_here = any(end == i + 1 for _start, end in protected)
                if ends_here and paragraph[i + 1:i + 2] in ("", "\n", "\r"):
                    if buffer.strip():
                        segments.append(buffer if preserve_whitespace else buffer.strip())
                    buffer = ""
                i += 1
                continue
            if re.match(f"[{escaped}]", ch):
                # zbierz ciąg znaków interpunkcyjnych i spacji
                j = i + 1
                while j < len(paragraph) and re.match(f"[{escaped}]", paragraph[j]):
                    buffer += paragraph[j]
                    j += 1
                trailing = ""
                # Separatorem po kropce jest KAŻDY biały znak, także nowa linia.
                # Wcześniej brano tylko spację i tabulator, więc zdania rozdzielone
                # znakiem końca wiersza sklejały się w jeden segment.
                while j < len(paragraph) and paragraph[j] in " \t\r\n":
                    trailing += paragraph[j]
                    j += 1
                rest = paragraph[j:]
                if _is_sentence_end(buffer, rest, trailing, extra_abbreviations,
                                    require_uppercase, skip_after_numbers):
                    segments.append(buffer if preserve_whitespace else buffer.strip())
                    buffer = ""
                else:
                    buffer += trailing
                i = j
                continue
            i += 1
        if buffer.strip():
            segments.append(buffer if preserve_whitespace else buffer.strip())
    return segments


def _is_sentence_end(buffer: str, rest: str, trailing: str,
                     extra_abbreviations: Optional[set] = None,
                     require_uppercase: bool = False,
                     skip_after_numbers: bool = False) -> bool:
    if not rest.strip():
        return True
    if not trailing:
        # brak spacji po kropce -> zwykle liczba lub adres (np. 3.14, www.x.pl)
        return False

    # Reguła jak w OmegaT: zdanie kończy się tylko wtedy, gdy dalej jest
    # wielka litera. „w 1999. roku” nie jest wówczas dzielone.
    if require_uppercase:
        first = rest.lstrip()[:1]
        if first and first.isalpha() and not first.isupper():
            return False

    # liczba przed kropką („punkt 5. mówi…”)
    if skip_after_numbers and re.search(r"\d[.!?]+$", buffer.strip()):
        return False

    # skrót przed kropką?
    match = re.search(r"([A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż.]+)[.!?]+$", buffer.strip())
    if match:
        word = match.group(1).lower().rstrip(".")
        if word in ABBREVIATIONS:
            return False
        if extra_abbreviations and word in extra_abbreviations:
            return False
        if len(word) == 1:  # inicjał, np. "J. Kowalski"
            return False
    return True


def _split_on_codes(segments: List[str]) -> List[str]:
    """Dzieli dodatkowo po znacznikach \\n, \\p, <<KON>> (pliki gier)."""
    out: List[str] = []
    for segment in segments:
        parts = re.split(r"(\\[a-zA-Z]|<<[^<>]{1,24}>>)", segment)
        buffer = ""
        for part in parts:
            if re.fullmatch(r"\\[a-zA-Z]|<<[^<>]{1,24}>>", part or ""):
                buffer += part
                if buffer.strip():
                    out.append(buffer)
                buffer = ""
            else:
                buffer += part or ""
        if buffer.strip():
            out.append(buffer)
    return out


def _merge_short(segments: List[str], minimum: int) -> List[str]:
    """Dokleja segmenty krótsze niż `minimum` znaków do poprzedniego."""
    if minimum <= 0:
        return segments
    out: List[str] = []
    for segment in segments:
        if out and len(segment.strip()) < minimum:
            out[-1] = out[-1] + segment
        else:
            out.append(segment)
    return out


def join_segments(segments: List[str], join_with: str = " ") -> str:
    return join_with.join(segments)
