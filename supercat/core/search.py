"""Wyszukiwanie w segmentach projektu – wszystkie pliki naraz.

Odpowiada na potrzebę: „znajdź wyraz w przeglądanym pliku i w innych”.
Zwraca trafienia z informacją o pliku, numerze segmentu, miejscu (źródło /
tłumaczenie), liczbie wystąpień i fragmencie z kontekstem.

Wyszukiwanie jest odporne na znaczniki plików gier: przy ``ignore_codes``
``\\n``, ``\\p``, ``<<KON>>`` i twarde końce wiersza liczą się jak spacja,
więc fraza „STAMP CARD System” znajdzie ``STAMP CARD\\nSystem``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .textutil import NEWLINE_MARKER, context_snippet, find_matches, replace_matches

MODES = ("contains", "word", "exact", "regex")

MODE_LABELS = {
    "Zawiera": "contains",
    "Całe słowo": "word",
    "Dokładne": "exact",
    "Regex": "regex",
}


@dataclass
class SearchOptions:
    mode: str = "contains"
    case_sensitive: bool = False
    ignore_accents: bool = False
    ignore_codes: bool = True
    in_source: bool = True
    in_target: bool = True
    only_untranslated: bool = False
    only_translated: bool = False
    #: Ograniczenie do wybranych statusów (pusty zbiór = wszystkie).
    statuses: Optional[Sequence[str]] = None
    #: Czy uwzględniać segmenty pominięte.
    include_ignored: bool = True
    #: Filtry białych znaków (klucze `WHITESPACE_FILTERS`); pusty = bez filtru.
    whitespace: Optional[Sequence[str]] = None
    files: Optional[Sequence[str]] = None      # None = wszystkie pliki

    def as_kwargs(self) -> dict:
        return {
            "mode": self.mode,
            "case_sensitive": self.case_sensitive,
            "ignore_accents": self.ignore_accents,
            "ignore_codes": self.ignore_codes,
        }


@dataclass
class SearchHit:
    index: int                 # numer segmentu w całym projekcie
    file_name: str
    where: str                 # "źródło" | "tłumaczenie"
    count: int
    spans: List[Tuple[int, int]]
    snippet: str
    source: str
    target: str


@dataclass
class SearchResult:
    hits: List[SearchHit] = field(default_factory=list)
    error: str = ""

    @property
    def total_matches(self) -> int:
        return sum(h.count for h in self.hits)

    @property
    def segments(self) -> int:
        return len({h.index for h in self.hits})

    def by_file(self) -> Dict[str, List[SearchHit]]:
        out: Dict[str, List[SearchHit]] = {}
        for hit in self.hits:
            out.setdefault(hit.file_name, []).append(hit)
        return out

    def file_counts(self) -> Dict[str, int]:
        return {name: sum(h.count for h in hits) for name, hits in self.by_file().items()}

    def summary(self) -> str:
        if self.error:
            return f"❌ {self.error}"
        if not self.hits:
            return "Brak wyników"
        files = len(self.by_file())
        return (f"Znaleziono {self.total_matches} trafień "
                f"w {self.segments} segmentach, {files} plikach")


#: Statusy rozpoznawane przez wyszukiwarkę (klucz → etykieta).
#: Filtry białych znaków – szukanie „usterek”, których nie widać w tekście.
#: Spacja na początku wiersza to w plikach gier częsty błąd: zmienia wcięcie
#: dialogu, a w edytorze wygląda identycznie jak tekst bez niej.
WHITESPACE_FILTERS = {
    "leading": "␣ spacja na początku",
    "trailing": "spacja na końcu ␣",
    "double": "podwójna spacja",
    "tab": "→ tabulator",
    "mismatch": "≠ inne brzegi niż źródło",
}


def whitespace_issues(text: str) -> List[str]:
    """Rodzaje białych znaków znalezione w tekście (klucze `WHITESPACE_FILTERS`)."""
    found: List[str] = []
    if not text:
        return found
    if text[:1] in (" ", "\u00a0"):
        found.append("leading")
    if text[-1:] in (" ", "\u00a0"):
        found.append("trailing")
    # Wcięcie na brzegu to osobny przypadek („spacja na początku/końcu”),
    # więc podwójną spację liczymy wyłącznie WEWNĄTRZ tekstu — tak samo
    # jak robi to kontrola jakości.
    if re.search(r"\S[ \t]{2,}\S", text):
        found.append("double")
    if "\t" in text:
        found.append("tab")
    return found


def whitespace_spans(text: str, kind: str) -> List[Tuple[int, int]]:
    """Zakresy do podświetlenia dla danego rodzaju białego znaku."""
    if not text:
        return []
    if kind == "leading":
        end = len(text) - len(text.lstrip(" \u00a0"))
        return [(0, end)] if end else []
    if kind == "trailing":
        start = len(text.rstrip(" \u00a0"))
        return [(start, len(text))] if start < len(text) else []
    if kind == "double":
        return [(m.start(1), m.end(1))
                for m in re.finditer(r"\S([ \t]{2,})\S", text)]
    if kind == "tab":
        return [(m.start(), m.end()) for m in re.finditer(r"\t+", text)]
    return []


def _edges(text: str) -> Tuple[str, str]:
    """Białe znaki na początku i końcu tekstu."""
    stripped = text.strip(" \t\u00a0")
    if not stripped:
        return text, ""
    start = text.index(stripped[0]) if stripped else 0
    lead = text[:start]
    trail = text[len(text.rstrip(" \t\u00a0")):]
    return lead, trail


def edges_differ(source: str, target: str) -> bool:
    """Czy tłumaczenie ma inne wcięcie/spacje na brzegach niż źródło.

    W plikach gier spacja na brzegu jest znacząca — brak jej w tłumaczeniu
    przesuwa tekst w oknie dialogowym.
    """
    if not source or not target:
        return False
    return _edges(source) != _edges(target)


STATUS_FILTERS = {
    "new": "○ nowy",
    "draft": "✎ roboczy",
    "translated": "✓ przetłumaczony",
    "approved": "★ zatwierdzony",
    "ignored": "🚫 pominięty",
}


def segment_status(seg) -> str:
    """Status segmentu widziany przez wyszukiwarkę (pominięty ma pierwszeństwo)."""
    if getattr(seg, "ignored", False):
        return "ignored"
    status = getattr(seg, "status", "") or "new"
    return status if status in STATUS_FILTERS else "new"


def _status_matches(seg, opts: "SearchOptions") -> bool:
    """Czy segment przechodzi filtr statusów i pominięć."""
    status = segment_status(seg)
    if not opts.include_ignored and status == "ignored":
        return False
    if not opts.statuses:
        return True
    return status in set(opts.statuses)


def _file_of(seg) -> str:
    return getattr(seg, "file_name", "") or "(bez pliku)"


def search_segments(segments: Sequence, needle: str,
                    options: Optional[SearchOptions] = None,
                    newline_marker: Optional[str] = NEWLINE_MARKER) -> SearchResult:
    """Przeszukuje listę segmentów. Nie rzuca wyjątków – błąd regex trafia do `error`."""
    opts = options or SearchOptions()
    result = SearchResult()
    if not needle or not segments:
        return result
    allowed = set(opts.files) if opts.files is not None else None
    kwargs = opts.as_kwargs()

    for idx, seg in enumerate(segments):
        name = _file_of(seg)
        if allowed is not None and name not in allowed:
            continue
        translated = bool((getattr(seg, "target", "") or "").strip())
        if opts.only_untranslated and translated:
            continue
        if opts.only_translated and not translated:
            continue
        if not _status_matches(seg, opts):
            continue

        for where, text in (("źródło", getattr(seg, "source", "") or ""),
                            ("tłumaczenie", getattr(seg, "target", "") or "")):
            if where == "źródło" and not opts.in_source:
                continue
            if where == "tłumaczenie" and not opts.in_target:
                continue
            try:
                spans = find_matches(text, needle, **kwargs)
            except re.error as exc:
                result.error = f"Błędne wyrażenie regularne: {exc}"
                return result
            if not spans:
                continue
            result.hits.append(SearchHit(
                index=idx,
                file_name=name,
                where=where,
                count=len(spans),
                spans=spans,
                snippet=context_snippet(text, spans[0], newline_marker=newline_marker),
                source=getattr(seg, "source", "") or "",
                target=getattr(seg, "target", "") or "",
            ))
    return result


def search_whitespace(segments: Sequence, kinds: Sequence[str],
                      options: Optional[SearchOptions] = None,
                      newline_marker: Optional[str] = NEWLINE_MARKER) -> SearchResult:
    """Znajduje segmenty z wybranymi problemami białych znaków.

    Działa **bez frazy** — szukamy tego, czego w tekście nie widać:
    spacji na początku wiersza, na końcu, podwójnych spacji, tabulatorów
    oraz brzegów innych niż w źródle.
    """
    opts = options or SearchOptions()
    result = SearchResult()
    wanted = [k for k in kinds if k in WHITESPACE_FILTERS]
    if not wanted or not segments:
        return result
    allowed = set(opts.files) if opts.files is not None else None

    for idx, seg in enumerate(segments):
        name = _file_of(seg)
        if allowed is not None and name not in allowed:
            continue
        source = getattr(seg, "source", "") or ""
        target = getattr(seg, "target", "") or ""
        translated = bool(target.strip())
        if opts.only_untranslated and translated:
            continue
        if opts.only_translated and not translated:
            continue
        if not _status_matches(seg, opts):
            continue

        for where, text in (("źródło", source), ("tłumaczenie", target)):
            if where == "źródło" and not opts.in_source:
                continue
            if where == "tłumaczenie" and not opts.in_target:
                continue
            if not text:
                continue

            found = [k for k in whitespace_issues(text) if k in wanted]
            spans: List[Tuple[int, int]] = []
            for kind in found:
                spans.extend(whitespace_spans(text, kind))
            # „inne brzegi niż źródło” dotyczy wyłącznie tłumaczenia
            if ("mismatch" in wanted and where == "tłumaczenie"
                    and edges_differ(source, target)):
                found.append("mismatch")
                lead = len(target) - len(target.lstrip(" \t\u00a0"))
                if lead:
                    spans.append((0, lead))
            if not found:
                continue

            spans.sort()
            labels = ", ".join(WHITESPACE_FILTERS[k] for k in found)
            hit_span = spans[0] if spans else (0, min(len(text), 1))
            result.hits.append(SearchHit(
                index=idx,
                file_name=name,
                where=where,
                count=len(spans) or 1,
                spans=spans,
                snippet=f"{labels} — "
                        + context_snippet(text, hit_span, newline_marker=newline_marker),
                source=source,
                target=target,
            ))
    return result


def replace_in_segments(segments: Sequence, needle: str, replacement: str,
                        options: Optional[SearchOptions] = None,
                        in_target: bool = True, in_source: bool = False,
                        on_change: Optional[Callable] = None) -> Tuple[int, int]:
    """Zamiana w zakresie. Zwraca (liczba zmienionych segmentów, liczba zamian)."""
    opts = options or SearchOptions()
    allowed = set(opts.files) if opts.files is not None else None
    kwargs = opts.as_kwargs()
    changed = 0
    total = 0
    for seg in segments:
        if allowed is not None and _file_of(seg) not in allowed:
            continue
        translated = bool((getattr(seg, "target", "") or "").strip())
        if opts.only_untranslated and translated:
            continue
        if opts.only_translated and not translated:
            continue
        if not _status_matches(seg, opts):
            continue
        touched = False
        if in_target and seg.target:
            new, n = replace_matches(seg.target, needle, replacement, **kwargs)
            if n:
                seg.target = new
                total += n
                touched = True
        if in_source and seg.source:
            new, n = replace_matches(seg.source, needle, replacement, **kwargs)
            if n:
                seg.source = new
                total += n
                touched = True
        if touched:
            changed += 1
            if on_change is not None:
                on_change(seg)
    return changed, total
