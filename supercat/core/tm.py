"""Pamięć tłumaczeniowa (odpowiednik services/TranslationMemoryService.java).

Baza SQLite: <projekt>/tm/project_tm.db
Import/eksport TMX 1.4.

Wydajność
---------
Naiwna implementacja (pełny odczyt bazy + normalizacja każdego wpisu przy każdym
zapytaniu) dawała ~4,8 s na jedno wyszukanie przy 20 tys. wpisów. Tutaj:

* wpisy są trzymane w indeksie w pamięci (`_Index`) i normalizowane **raz**,
  a nie przy każdym zapytaniu,
* przed kosztownym porównaniem odrzucamy kandydatów po długości i po
  wspólnych tokenach (dopasowanie ≥ próg wymaga podobnej długości),
* właściwe podobieństwo liczy `rapidfuzz` (SIMD), a gdy go nie ma –
  `difflib` z tanimi filtrami wstępnymi,
* jest wersja wsadowa `find_best_matches_batch` dla operacji masowych.
"""
from __future__ import annotations

import os
import re
import sqlite3
import threading
import time
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .settings import SettingsManager
from .tags import adapt_codes, adapt_translation, normalize_tags_for_comparison

try:  # numpy pozwala wybrać najlepsze wyniki bez sortowania całej macierzy
    import numpy as _np

    HAS_NUMPY = True
except ImportError:  # pragma: no cover
    HAS_NUMPY = False

try:  # przyspieszenie opcjonalne – program działa też bez tej biblioteki
    from rapidfuzz import fuzz as _rf_fuzz
    from rapidfuzz import process as _rf_process
    from rapidfuzz.distance import Levenshtein as _rf_lev

    HAS_RAPIDFUZZ = True
except ImportError:  # pragma: no cover
    HAS_RAPIDFUZZ = False

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

#: Minimalna część słów linii segmentu, jaką musi pokryć wpis z pamięci.
#: Bez tego progu jednowyrazowy wpis („System”) uchodził za dopasowanie całej
#: linii („GIFT System.”) i wypierał sensowne podpowiedzi. Sama proporcja
#: długości tu nie wystarcza – rozstrzyga dopiero pokrycie słów.
_MIN_LINE_WORD_COVERAGE = 0.6


@dataclass
class TranslationMatch:
    original_source: str
    original_target: str
    adapted_target: str
    similarity: int
    exact: bool = False

    @property
    def text(self) -> str:
        if SettingsManager.instance().get_bool("tm.adapt.tags", True):
            return self.adapted_target
        return self.original_target


@dataclass
class SentenceMatch:
    """Dopasowanie fragmentu zdania (odpowiednik findSentenceMatches z repo `5`).

    `fragment_source` to fragment znaleziony w TM, `assembled` to segment
    źródłowy z podstawionym tłumaczeniem tego fragmentu.
    """

    fragment_source: str
    fragment_target: str
    assembled: str
    coverage: int  # jaki % znaków segmentu pokrywa fragment
    #: Pary (linia źródłowa, linia tłumaczenia) – rozbicie wpisu TM po \n / \p.
    line_pairs: List[Tuple[str, str]] = field(default_factory=list)
    #: Skąd pochodzi dopasowanie: "fragment", "linia" lub "złożenie".
    kind: str = "fragment"
    #: True, gdy w złożonej propozycji został nieprzetłumaczony tekst źródłowy.
    partial: bool = False

    @property
    def label(self) -> str:
        """Opis dla listy podpowiedzi — z ostrzeżeniem o niepełnym złożeniu."""
        base = f"{self.kind} • pokrycie {self.coverage}%"
        return f"⚠️ {base} • zostaje tekst źródłowy" if self.partial else base

    @property
    def text(self) -> str:
        return self.assembled


#: Tablica zamiany znaków diakrytycznych. `str.translate` działa w C i jest
#: kilkanaście razy szybsze niż rozkład NFD + sprawdzanie kategorii Unicode
#: dla każdego znaku (przy 10 tys. wpisów to były ~1,6 mln wywołań).
_ACCENT_MAP = str.maketrans({
    "ą": "a", "ć": "c", "ę": "e", "ł": "l", "ń": "n", "ó": "o", "ś": "s",
    "ź": "z", "ż": "z", "Ą": "A", "Ć": "C", "Ę": "E", "Ł": "L", "Ń": "N",
    "Ó": "O", "Ś": "S", "Ź": "Z", "Ż": "Z",
    "á": "a", "à": "a", "â": "a", "ä": "a", "ã": "a", "å": "a",
    "é": "e", "è": "e", "ê": "e", "ë": "e",
    "í": "i", "ì": "i", "î": "i", "ï": "i",
    "ò": "o", "ô": "o", "ö": "o", "õ": "o",
    "ú": "u", "ù": "u", "û": "u", "ü": "u",
    "ý": "y", "ÿ": "y", "ñ": "n", "ç": "c",
    "š": "s", "ž": "z", "č": "c", "ř": "r", "ě": "e", "ů": "u", "ď": "d",
    "ť": "t", "ň": "n", "ĺ": "l", "ľ": "l", "ŕ": "r", "ő": "o", "ű": "u",
    "Á": "A", "À": "A", "Â": "A", "Ä": "A", "Ã": "A", "Å": "A",
    "É": "E", "È": "E", "Ê": "E", "Ë": "E",
    "Í": "I", "Ì": "I", "Î": "I", "Ï": "I",
    "Ò": "O", "Ô": "O", "Ö": "O", "Õ": "O",
    "Ú": "U", "Ù": "U", "Û": "U", "Ü": "U",
    "Ý": "Y", "Ñ": "N", "Ç": "C",
    "Š": "S", "Ž": "Z", "Č": "C", "Ř": "R", "Ě": "E", "Ů": "U",
})

#: Znaki spoza tablicy (rzadkie alfabety) trafiają na wolniejszą ścieżkę.
_NON_ASCII_RE = re.compile(r"[^\x00-\x7F]")


def _strip_accents(text: str) -> str:
    """Usuwa znaki diakrytyczne. Szybka ścieżka dla tekstu ASCII i typowych liter."""
    if text.isascii():
        return text
    result = text.translate(_ACCENT_MAP)
    if result.isascii():
        return result
    # rzadki przypadek: alfabet spoza tablicy – pełna normalizacja Unicode
    normalized = unicodedata.normalize("NFD", result)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


#: Znaczniki sterujące spotykane w plikach gier / CAT: literalne \n \p \l \r \c
#: oraz ich odpowiedniki jako prawdziwe znaki sterujące.
_CONTROL_CODE_RE = re.compile(r"\\[npNPlLrRcC]")


def unify_control_codes(text: str) -> str:
    """Sprowadza znaczniki końca linii do jednej postaci na potrzeby porównań.

    W plikach CAT ta sama treść bywa zapisana raz jako literalne ``\\n``
    (backslash + litera), a raz jako prawdziwy znak nowej linii. Bez ujednolicenia
    wpis TM „Thank you for using the MYSTERY\\nGIFT System.” nie pasuje do segmentu
    zawierającego prawdziwy przełam wiersza. Wszystkie warianty zamieniamy na
    zwykłą spację, dzięki czemu porównanie patrzy wyłącznie na treść.
    """
    if not text:
        return ""
    result = _CONTROL_CODE_RE.sub(" ", text)
    result = result.replace("\r\n", " ").replace("\n", " ").replace("\r", " ").replace("\t", " ")
    return re.sub(r"\s+", " ", result).strip()


def _adapt_to_segment(source: str, target: str) -> str:
    """Dopasowuje podpowiedź TM do bieżącego segmentu.

    Najpierw tagi (``adapt_translation``), potem pozycje znaczników
    ``\\n``/``\\l``/``\\p`` — dzięki temu tłumaczenie z pamięci przełamuje
    się w tych samych miejscach co oryginał (ustawienie ``tm.adapt.codes``).
    """
    out = adapt_translation(source, target)
    sm = SettingsManager.instance()
    if sm.get_bool("tm.adapt.codes", True):
        from .tags import (DEFAULT_LINE_BREAKS, DEFAULT_PARA_BREAKS,
                           parse_break_codes)
        line_codes = parse_break_codes(
            sm.get_str("tm.adapt.line.codes", "\\n \\l"), DEFAULT_LINE_BREAKS)
        para_codes = parse_break_codes(
            sm.get_str("tm.adapt.para.codes", "\\p"), DEFAULT_PARA_BREAKS)
        from .tags import effective_break_codes, parse_code_list
        _esc, _inl = parse_code_list(sm.get_str("tm.codes.list", ""))
        line_codes, para_codes = effective_break_codes(
            source, line_codes, para_codes,
            extra_codes=_esc, auto_detect=not (_esc or _inl))
        out = adapt_codes(source, out, line_codes, para_codes,
                          smart=sm.get_bool("tm.adapt.codes.smart", True))
    return out


def _norm_key(text: str) -> str:
    """Klucz porównawczy: bez tagów i znaczników linii, bez akcentów, małe litery."""
    return _strip_accents(unify_control_codes(normalize_tags_for_comparison(text or "")).lower())


def similarity_percent(a: str, b: str) -> int:
    """Podobieństwo dwóch napisów w procentach (0-100)."""
    if not a or not b:
        return 0
    if a == b:
        return 100
    n1, n2 = _strip_accents(a.lower()), _strip_accents(b.lower())
    if n1 == n2:
        return 100
    if HAS_RAPIDFUZZ:
        return int(round(_rf_fuzz.ratio(n1, n2)))
    return int(round(SequenceMatcher(None, n1, n2).ratio() * 100))


class _Index:
    """Indeks TM w pamięci: znormalizowane klucze + tokeny do filtrowania."""

    __slots__ = ("sources", "targets", "keys", "lengths", "token_sets", "flats",
                 "_by_key", "variants", "word_index", "_indexed_upto",
                 "_len_array", "_len_upto")

    def __init__(self) -> None:
        self.sources: List[str] = []
        self.targets: List[str] = []
        self.keys: List[str] = []
        self.lengths: List[int] = []
        self.token_sets: List[frozenset] = []
        #: Tekst źródłowy po spłaszczeniu (bez \n, akcentów, małe litery) –
        #: liczony RAZ przy dodaniu, bo przeliczanie go przy każdym zapytaniu
        #: było najdroższą operacją w dopasowaniu zdań.
        self.flats: List[str] = []
        self._by_key: Dict[str, int] = {}
        #: Dodatkowe tłumaczenia tego samego źródła (numer wpisu -> lista).
        #: Pierwszy element to wariant główny, czyli ten z początku pliku TM.
        self.variants: Dict[int, List[str]] = {}
        #: Indeks odwrotny: słowo -> numery wpisów. Pozwala pominąć pełny
        #: przegląd pamięci przy każdym wyszukiwaniu.
        self.word_index: Dict[str, List[int]] = {}
        self._indexed_upto = 0
        #: Długości kluczy jako tablica numpy – filtrowanie wektorowe zamiast pętli
        self._len_array = None
        self._len_upto = 0

    def __len__(self) -> int:
        return len(self.sources)

    def clear(self) -> None:
        self.sources.clear()
        self.targets.clear()
        self.keys.clear()
        self.lengths.clear()
        self.token_sets.clear()
        self.flats.clear()
        self._by_key.clear()
        self.variants.clear()
        self.word_index.clear()
        self._indexed_upto = 0
        self._len_array = None
        self._len_upto = 0

    def add(self, source: str, target: str, keep_variants: bool = True) -> None:
        """Dokłada wpis do indeksu, zachowując **warianty** tego samego źródła.

        To samo zdanie angielskie bywa tłumaczone różnie zależnie od miejsca
        w grze (``BALL`` → ``KULA`` / ``PIŁKA`` / ``BAL``). Wcześniej kolejny
        wpis **nadpisywał** poprzedni, więc zostawało wyłącznie ostatnie
        tłumaczenie z pliku, a pozostałe znikały bezpowrotnie. Teraz pierwszy
        wariant zostaje głównym (jest podpowiadany domyślnie), a kolejne
        trafiają na listę alternatyw dostępną w podpowiedziach TM.
        """
        key = _norm_key(source)
        existing = self._by_key.get(key)
        if existing is not None and self.sources[existing] == source:
            current = self.targets[existing]
            if target == current:
                return
            variants = self.variants.setdefault(existing, [current])
            if target not in variants:
                # Import z pliku: kolejność z pliku, nowy wariant na końcu.
                # Zapis od tłumacza: jego wersja staje się główną podpowiedzią.
                variants.insert(len(variants) if keep_variants else 0, target)
            if not keep_variants:
                self.targets[existing] = target
            return
        self._by_key[key] = len(self.sources)
        self.sources.append(source)
        self.targets.append(target)
        self.keys.append(key)
        self.lengths.append(len(key))
        self.token_sets.append(frozenset(_TOKEN_RE.findall(key)))
        self.flats.append(_flatten_text(source))

    def variants_for(self, position: int) -> List[str]:
        """Wszystkie tłumaczenia danego źródła — pierwsze z pliku na początku."""
        return list(self.variants.get(position, [self.targets[position]]))

    def length_array(self):
        """Zwraca tablicę numpy z długościami kluczy (budowana przyrostowo)."""
        if not HAS_NUMPY:
            return None
        total = len(self.lengths)
        if self._len_array is None or self._len_upto != total:
            self._len_array = _np.fromiter(self.lengths, dtype=_np.int32, count=total)
            self._len_upto = total
        return self._len_array

    def build_word_index(self, yield_every: int = 4000) -> None:
        """Buduje/uzupełnia indeks odwrotny słów (przyrostowo)."""
        start = self._indexed_upto
        total = len(self.flats)
        if start >= total:
            return
        index = self.word_index
        for i in range(start, total):
            for word in set(_TOKEN_RE.findall(self.flats[i])):
                if len(word) >= 3:
                    index.setdefault(word, []).append(i)
            if yield_every and (i - start) and (i - start) % yield_every == 0:
                time.sleep(0)
        self._indexed_upto = total

    def candidates_for(self, text: str, max_candidates: int = 4000) -> Optional[List[int]]:
        """Numery wpisów dzielących słowo z podanym tekstem (None = brak filtra)."""
        words = {w for w in _TOKEN_RE.findall(text) if len(w) >= 3}
        if not words:
            return None
        self.build_word_index()
        total = len(self.flats)
        if not total:
            return None

        # Słowa pospolite (np. „system”, „numer”) występują niemal wszędzie
        # i nic nie zawężają. Bierzemy najpierw najrzadsze i dokładamy kolejne,
        # dopóki zbiór kandydatów pozostaje wyraźnie mniejszy od całej pamięci.
        buckets = [(len(self.word_index.get(w, ())), w) for w in words]
        buckets = [(n, w) for n, w in buckets if n]
        if not buckets:
            return None
        buckets.sort()

        cap = min(max_candidates, max(1, total // 2))
        found: set[int] = set()
        for count, word in buckets:
            if found and len(found) + count > cap:
                continue        # to słowo rozdęłoby zbiór ponad limit
            found.update(self.word_index[word])
            if len(found) >= cap:
                break
        if not found or len(found) >= total:
            return None         # brak zawężenia – taniej przejrzeć wszystko
        return sorted(found)

    def build(self, rows: Iterable[Tuple[str, str]], yield_every: int = 500) -> None:
        """Buduje indeks, oddając GIL co `yield_every` wpisów.

        Przy dużych pamięciach (dziesiątki tysięcy wpisów) pętla bez przerw
        blokowała wątek interfejsu na sekundy – okno wyraźnie „muliło”.
        """
        self.clear()
        for n, (source, target) in enumerate(rows, 1):
            self.add(source, target)
            if yield_every and n % yield_every == 0:
                time.sleep(0)


def write_tmx(path: str, rows, source_lang: str = "en",
              target_lang: str = "pl") -> int:
    """Zapisuje pary tłumaczeń do pliku TMX 1.4.

    Przyjmuje krotki ``(źródło, tłumaczenie[, język_źr, język_doc])``, więc
    korzysta z niej zarówno eksport pamięci, jak i generator TM z plików —
    format zapisu jest jeden i nie rozjedzie się między funkcjami.
    """
    folder = os.path.dirname(os.path.abspath(path))
    if folder:
        os.makedirs(folder, exist_ok=True)
    count = 0
    with open(path, "w", encoding="utf-8") as handle:
        handle.write('<?xml version="1.0" encoding="UTF-8"?>\n<tmx version="1.4">\n')
        handle.write(
            '  <header creationtool="SuperCAT" creationtoolversion="1.0" segtype="sentence" '
            f'o-tmf="SuperCAT" adminlang="en" srclang="{source_lang}" datatype="plaintext" '
            f'creationdate="{time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())}"/>\n  <body>\n'
        )
        for row in rows:
            source, target = row[0], row[1]
            row_sl = row[2] if len(row) > 2 and row[2] else source_lang
            row_tl = row[3] if len(row) > 3 and row[3] else target_lang
            handle.write("    <tu>\n")
            handle.write(f'      <tuv xml:lang="{_xml_attr(row_sl)}">'
                         f'<seg>{_xml_escape(source)}</seg></tuv>\n')
            handle.write(f'      <tuv xml:lang="{_xml_attr(row_tl)}">'
                         f'<seg>{_xml_escape(target)}</seg></tuv>\n')
            handle.write("    </tu>\n")
            count += 1
        handle.write("  </body>\n</tmx>\n")
    return count


class TranslationMemory:
    def __init__(self) -> None:
        self._conn: Optional[sqlite3.Connection] = None
        self.db_path: Optional[str] = None
        self._index = _Index()
        self._dirty = True
        #: Cache linii TM (równoległe listy – bez kopiowania przy każdym zapytaniu)
        self._line_keys: List[str] = []        # linia źródłowa, znormalizowana
        self._line_src: List[str] = []         # linia źródłowa, oryginał
        self._line_tgt: List[str] = []         # odpowiadająca linia tłumaczenia
        self._line_cache_size = -1
        #: Indeks i cache są czytane z wątków roboczych, a zmieniane z wątku GUI.
        #: Bez tej blokady dochodziło do wyścigu i zawieszenia programu.
        self._lock = threading.RLock()
        #: Odroczony commit – przy szybkim zatwierdzaniu segmentów zapis na dysk
        #: po każdym wpisie niepotrzebnie zacinał interfejs.
        self._pending_commit = False
        self._last_commit = 0.0

    # ------------------------------------------------------------------
    @property
    def is_initialized(self) -> bool:
        return self._conn is not None

    def init_for_project(self, tm_folder: str) -> None:
        db_path = os.path.join(tm_folder, "project_tm.db")
        if db_path == self.db_path and self._conn is not None:
            return
        self.close()
        os.makedirs(tm_folder, exist_ok=True)
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        # WAL + większy cache => szybszy import i zapis
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA cache_size=-40000")
            self._conn.execute("PRAGMA temp_store=MEMORY")
        except sqlite3.Error:
            pass
        self._create_tables()
        self._reload_index()

    def _create_tables(self) -> None:
        assert self._conn
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS translation_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_text TEXT NOT NULL,
                target_text TEXT NOT NULL,
                source_lang TEXT DEFAULT 'en',
                target_lang TEXT DEFAULT 'pl',
                created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                usage_count INTEGER DEFAULT 0,
                UNIQUE(source_text, target_text)
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_source ON translation_memory(source_text)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_usage ON translation_memory(usage_count DESC)")
        self._conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._pending_commit = False
                self._conn.commit()
                self._conn.close()
            except Exception:
                pass
        self._conn = None
        self.db_path = None
        self._index.clear()
        self._dirty = True
        self._reset_line_cache()

    def _reset_line_cache(self) -> None:
        """Czyści cache linii (musi iść w parze z każdą zmianą indeksu)."""
        self._line_keys = []
        self._line_src = []
        self._line_tgt = []
        self._line_cache_size = -1

    # ----------------------------------------------------------- indeks
    def _reload_index(self) -> None:
        if not self._conn:
            return
        # ORDER BY id — indeks musi odzwierciedlać kolejność wpisów w pliku TM.
        # Bez tego przy kilku tłumaczeniach tego samego źródła („BALL” → KULA /
        # PIŁKA / BAL) wygrywał przypadkowy wiersz, a nie pierwszy z pliku.
        rows = self._conn.execute(
            "SELECT source_text, target_text FROM translation_memory ORDER BY id")
        self._index.build(rows)
        self._dirty = False
        self._reset_line_cache()

    def _ensure_index(self) -> None:
        with self._lock:
            if self._dirty:
                self._reload_index()

    # ------------------------------------------------------------------
    def add(self, source: str, target: str, source_lang: str = "en", target_lang: str = "pl") -> bool:
        if not self._conn or not source or not source.strip() or target is None:
            return False
        source, target = source.strip(), target.strip()
        if not target:
            return False
        # Opcja „Nie zapisuj do TM tekstów w języku źródłowym” (Ustawienia →
        # Pamięć TM). Chroni pamięć przed wpisami typu „Save the game” →
        # „Save the game”, które później podpowiadają same siebie.
        if SettingsManager.instance().get_bool("tm.reject.untranslated", False):
            from .tm_builder import is_untranslated

            if is_untranslated(source, target):
                return False
        self._conn.execute(
            """
            INSERT INTO translation_memory (source_text, target_text, source_lang, target_lang, usage_count)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(source_text, target_text)
            DO UPDATE SET usage_count = usage_count + 1
            """,
            (source, target, source_lang, target_lang),
        )
        self._deferred_commit()
        with self._lock:
            # Ręczny zapis tłumaczenia zastępuje poprzednie; warianty z pliku
            # TM buduje wyłącznie import (_reload_index / add_many).
            self._index.add(source, target, keep_variants=False)
        return True

    def _deferred_commit(self, force: bool = False) -> None:
        """Zapisuje zmiany na dysk, ale nie częściej niż raz na sekundę."""
        self._pending_commit = True
        now = time.monotonic()
        if force or now - self._last_commit >= 1.0:
            try:
                self._conn.commit()
            except Exception:
                pass
            self._pending_commit = False
            self._last_commit = now

    def flush(self) -> None:
        """Wymusza zapis oczekujących zmian (przy zapisie projektu / zamknięciu)."""
        if self._conn is not None and self._pending_commit:
            self._deferred_commit(force=True)

    def add_many(self, rows: Sequence[Tuple[str, str, str, str]]) -> int:
        if not self._conn or not rows:
            return 0
        cur = self._conn.cursor()
        cur.executemany(
            """
            INSERT INTO translation_memory (source_text, target_text, source_lang, target_lang, usage_count)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(source_text, target_text) DO UPDATE SET usage_count = usage_count + 1
            """,
            rows,
        )
        self._conn.commit()
        self._dirty = True
        return len(rows)

    def delete(self, source: str, target: str) -> None:
        if not self._conn:
            return
        self._conn.execute(
            "DELETE FROM translation_memory WHERE source_text = ? AND target_text = ?", (source, target)
        )
        self._conn.commit()
        with self._lock:
            self._dirty = True
            self._reset_line_cache()

    def clear(self) -> None:
        if not self._conn:
            return
        self._conn.execute("DELETE FROM translation_memory")
        self._conn.commit()
        with self._lock:
            self._index.clear()
            self._dirty = False
            self._reset_line_cache()

    def size(self) -> int:
        """Liczba wpisów w pamięci.

        Połączenie SQLite jest współdzielone przez wątki (``check_same_thread=False``),
        więc przy równoczesnym zapisie z innego wątku `fetchone()` potrafi zwrócić
        ``None`` – wtedy zamiast wywrócić wątek rozgrzewki oddajemy rozmiar indeksu.
        """
        if not self._conn:
            return 0
        self.flush()
        try:
            row = self._conn.execute("SELECT COUNT(*) FROM translation_memory").fetchone()
        except sqlite3.Error:
            row = None
        if row is None or row[0] is None:
            with self._lock:
                return len(self._index)
        return int(row[0])

    def all_entries(self, limit: int = 0) -> List[Tuple[str, str, str, str, int]]:
        if not self._conn:
            return []
        # Kolejność jak w pliku TM (rosnące id). Wcześniejsze sortowanie po
        # liczniku użyć przestawiało wpisy, przez co eksport TMX i podgląd
        # pamięci nie odpowiadały plikowi źródłowemu.
        sql = (
            "SELECT source_text, target_text, source_lang, target_lang, usage_count "
            "FROM translation_memory ORDER BY id"
        )
        if limit:
            sql += f" LIMIT {int(limit)}"
        return list(self._conn.execute(sql))

    def search(self, query: str, limit: int = 200) -> List[Tuple[str, str, str, str, int]]:
        """Wyszukiwanie konkordancji (source LUB target zawiera query)."""
        if not self._conn or not query:
            return []
        like = f"%{query}%"
        return list(
            self._conn.execute(
                """
                SELECT source_text, target_text, source_lang, target_lang, usage_count
                FROM translation_memory
                WHERE source_text LIKE ? COLLATE NOCASE OR target_text LIKE ? COLLATE NOCASE
                ORDER BY usage_count DESC LIMIT ?
                """,
                (like, like, limit),
            )
        )

    # --------------------------------------------------- dopasowania fuzzy
    def _candidates(self, key: str, threshold: int) -> List[int]:
        """Wstępne odsianie kandydatów – tanie testy zamiast pełnego porównania.

        Dopasowanie ≥ threshold% wymaga zbliżonej długości napisów, więc wpisy
        poza oknem długości można odrzucić bez liczenia odległości edycyjnej.
        """
        self._ensure_index()
        n = len(key)
        if n == 0:
            return []
        ratio = threshold / 100.0
        min_len, max_len = int(n * ratio), (int(n / ratio) + 1 if ratio > 0 else 10 ** 9)

        # Najpierw zawężamy po słowach (indeks odwrotny), potem filtrujemy
        # długość. Oba kroki są wektorowe – pętla po całej pamięci kosztowała
        # kilkanaście ms przy każdym wyszukiwaniu.
        narrowed = self._index.candidates_for(key)

        lengths_np = self._index.length_array()
        if lengths_np is not None:
            if narrowed is not None:
                idx = _np.fromiter(narrowed, dtype=_np.int64, count=len(narrowed))
                sel = lengths_np[idx]
                mask = (sel >= min_len) & (sel <= max_len)
                return idx[mask].tolist()
            mask = (lengths_np >= min_len) & (lengths_np <= max_len)
            return _np.flatnonzero(mask).tolist()

        lengths = self._index.lengths
        source_iter = narrowed if narrowed is not None else range(len(lengths))
        return [i for i in source_iter if min_len <= lengths[i] <= max_len]

    def find_fuzzy_matches(self, source: str, threshold: int = 70, limit: int = 5) -> List[TranslationMatch]:
        """Znajduje dopasowania rozmyte z adaptacją tagów."""
        if not self._conn or not source or not source.strip():
            return []
        self._ensure_index()
        key = _norm_key(source)
        if not key:
            return []

        candidates = self._candidates(key, threshold)
        if not candidates:
            return []

        keys = self._index.keys
        scored: List[Tuple[int, int]] = []  # (similarity, index)

        if HAS_RAPIDFUZZ:
            # porcjami, żeby długie wywołanie nie trzymało GIL bez przerwy
            block = 20000
            if len(candidates) > block:
                for start in range(0, len(candidates), block):
                    part = {i: keys[i] for i in candidates[start:start + block]}
                    scored.extend(
                        (int(round(score)), idx)
                        for _text, score, idx in _rf_process.extract(
                            key, part, scorer=_rf_fuzz.ratio, score_cutoff=threshold,
                            limit=max(limit * 4, 20),
                        )
                    )
                    time.sleep(0)
            else:
                choices = {i: keys[i] for i in candidates}
                scored = [
                    (int(round(score)), idx)
                    for _text, score, idx in _rf_process.extract(
                        key, choices, scorer=_rf_fuzz.ratio, score_cutoff=threshold,
                        limit=max(limit * 4, 20),
                    )
                ]
        else:
            matcher = SequenceMatcher()
            matcher.set_seq2(key)
            cutoff = threshold / 100.0
            for i in candidates:
                matcher.set_seq1(keys[i])
                # trzystopniowy filtr: tanie testy przed pełnym porównaniem
                if matcher.real_quick_ratio() < cutoff or matcher.quick_ratio() < cutoff:
                    continue
                ratio = matcher.ratio()
                if ratio >= cutoff:
                    scored.append((int(round(ratio * 100)), i))

        if not scored:
            return []
        scored.sort(key=lambda t: -t[0])

        filter_untranslated = SettingsManager.instance().get_bool("tm.filter.english", True)
        matches: List[TranslationMatch] = []
        seen: set[str] = set()
        for sim, i in scored:
            db_source = self._index.sources[i]
            # Warianty tego samego źródła (np. BALL → KULA / PIŁKA / BAL)
            # pokazujemy jako osobne podpowiedzi — w kolejności z pliku TM.
            for db_target in self._index.variants_for(i):
                if db_target in seen:
                    continue
                if filter_untranslated and _is_mostly_untranslated(db_source, db_target):
                    continue
                seen.add(db_target)
                matches.append(
                    TranslationMatch(db_source, db_target,
                                     _adapt_to_segment(source, db_target),
                                     sim, sim == 100)
                )
                if len(matches) >= limit:
                    return matches
        return matches

    def find_best_matches_batch(
        self,
        sources: Sequence[str],
        threshold: int = 80,
        progress: Optional[Callable[[int, int], bool]] = None,
    ) -> List[Optional[TranslationMatch]]:
        """Najlepsze dopasowanie dla wielu segmentów naraz (dla „Zastosuj TM”).

        `progress(done, total)` może zwrócić False, aby przerwać. Indeks jest
        wczytywany raz dla całej partii, stąd duży zysk względem wywołań
        pojedynczych.
        """
        self._ensure_index()
        total = len(sources)
        results: List[Optional[TranslationMatch]] = [None] * total
        if not self._conn or not len(self._index):
            return results

        filter_untranslated = SettingsManager.instance().get_bool("tm.filter.english", True)
        keys = self._index.keys
        cutoff = threshold / 100.0

        for pos, source in enumerate(sources):
            if progress is not None and pos % 25 == 0:
                if progress(pos, total) is False:
                    break
            if not source or not source.strip():
                continue
            key = _norm_key(source)
            candidates = self._candidates(key, threshold)
            if not candidates:
                continue

            best_score, best_idx = 0, -1
            if HAS_RAPIDFUZZ:
                choices = {i: keys[i] for i in candidates}
                hit = _rf_process.extractOne(
                    key, choices, scorer=_rf_fuzz.ratio, score_cutoff=threshold
                )
                if hit:
                    best_score, best_idx = int(round(hit[1])), hit[2]
            else:
                matcher = SequenceMatcher()
                matcher.set_seq2(key)
                for i in candidates:
                    matcher.set_seq1(keys[i])
                    if matcher.real_quick_ratio() < cutoff or matcher.quick_ratio() < cutoff:
                        continue
                    ratio = matcher.ratio()
                    if ratio >= cutoff and ratio * 100 > best_score:
                        best_score, best_idx = int(round(ratio * 100)), i

            if best_idx < 0:
                continue
            db_source, db_target = self._index.sources[best_idx], self._index.targets[best_idx]
            if filter_untranslated and _is_mostly_untranslated(db_source, db_target):
                continue
            results[pos] = TranslationMatch(
                db_source, db_target, _adapt_to_segment(source, db_target), best_score, best_score == 100
            )

        if progress is not None:
            progress(total, total)
        return results

    # ------------------------------------------- dopasowanie zdań (fragmenty)
    def add_volatile_pairs(self, pairs: Sequence[Tuple[str, str]]) -> None:
        """Dokłada do indeksu pary tłumaczeń **bez zapisu do bazy**.

        Używane dla segmentów przetłumaczonych w bieżącej sesji: podpowiedzi
        TM i dopasowanie zdań widzą je od razu, jeszcze zanim trafią do pamięci.
        """
        with self._lock:
            for source, target in pairs:
                if not source or not source.strip() or not target or not target.strip():
                    continue
                key = _norm_key(source)
                existing = self._index._by_key.get(key)
                if existing is not None and self._index.targets[existing] == target.strip():
                    continue
                self._index.add(source.strip(), target.strip())
            # cache uzupełni się przyrostowo przy następnym wyszukiwaniu

    def find_sentence_matches(self, segment: str, limit: int = 25,
                              should_cancel: Optional[Callable[[], bool]] = None) -> List[SentenceMatch]:
        """Dopasowanie rozbitych zdań – odpowiednik `findSentenceMatches` z repo `5`.

        Szuka w TM wpisów, których tekst źródłowy jest **fragmentem** bieżącego
        segmentu, i składa propozycję: segment z podstawionym tłumaczeniem
        fragmentu. Przydatne, gdy segmentacja rozbiła zdanie inaczej niż w TM.
        """
        if not self._conn or not segment or len(segment.strip()) < 3:
            return []
        settings = SettingsManager.instance()
        if not settings.get_bool("tm.sentence.matching.enabled", False):
            return []
        if should_cancel is not None and should_cancel():
            return []
        self._ensure_index()

        # Zabezpieczenie: przy bardzo dużych pamięciach dopasowanie zdań potrafi
        # trwać sekundy i (przez GIL) spowalniać interfejs. Powyżej limitu
        # funkcja jest pomijana – limit ustawia się w Ustawieniach → Pamięć TM.
        max_units = settings.get_int("tm.sentence.max.units", 20000)
        if max_units and len(self._index) > max_units:
            return []

        haystack = segment
        # Mapa: pozycja w tekście „spłaszczonym” -> pozycja w oryginale.
        # Dzięki temu szukamy po treści (bez \n, \p, tagów), a podmieniamy
        # dokładnie ten wycinek oryginału, zachowując oryginalne znaczniki.
        flat, flat_to_orig = _flatten_with_map(haystack)
        filter_untranslated = SettingsManager.instance().get_bool("tm.filter.english", True)

        # 1) zbierz wszystkie fragmenty TM występujące w segmencie (z pozycjami)
        hits: List[Tuple[int, int, str, str]] = []  # (start, end, source, target)
        seen: set[str] = set()
        if should_cancel is not None and should_cancel():
            return []
        # tylko wpisy dzielące słowo z segmentem – zamiast całej pamięci
        scan = self._index.candidates_for(flat)
        if scan is None:
            scan = range(len(self._index.sources))
        flats_all = self._index.flats
        # Odrzuć po długości ZANIM sięgniemy po tekst: wpis dłuższy niż segment
        # nie może być jego fragmentem. Filtr wektorowy zamiast pętli z `len`.
        lengths_np = self._index.length_array()
        flat_len = len(flat)
        if lengths_np is not None and not isinstance(scan, range):
            idx = _np.fromiter(scan, dtype=_np.int64, count=len(scan))
            if idx.size:
                sel = lengths_np[idx]
                scan = idx[(sel > 3) & (sel < flat_len)].tolist()
            else:
                scan = []
        for i in scan:
            needle = flats_all[i]
            if len(needle) <= 3 or len(needle) >= flat_len:
                continue
            start = flat.find(needle)
            if start < 0:
                continue
            db_source = self._index.sources[i]
            db_target = self._index.targets[i]
            if db_target in seen:
                continue
            if filter_untranslated and _is_mostly_untranslated(db_source, db_target):
                continue
            seen.add(db_target)
            # przelicz pozycje z tekstu spłaszczonego na oryginalny
            orig_start = flat_to_orig[start]
            orig_end = flat_to_orig[start + len(needle) - 1] + 1
            hits.append((orig_start, orig_end, db_source, db_target))

        # 1b) dopasowanie LINIA PO LINII – wpis TM obejmujący kilka linii
        #     (np. "Thank you for using the MYSTERY\nGIFT System.") jest rozbijany
        #     po \n / \p i pokazywany jako osobne pary linii.
        seg_lines = split_lines_by_codes(segment)
        line_matches: List[SentenceMatch] = []
        if len(seg_lines) > 1 or hits:
            seen_line_pairs: set[str] = set()
            flats = self._index.flats
            for i in scan:
                db_source = self._index.sources[i]
                # NAJPIERW tani test przynależności – dopiero potem kosztowne
                # rozbijanie na linie. Odwrotna kolejność powodowała 50 tys.
                # wywołań align_lines przy każdym wyszukiwaniu (71% czasu).
                db_flat = flats[i]
                if not db_flat or db_flat not in flat:
                    continue
                db_target = self._index.targets[i]
                pairs = align_lines(db_source, db_target)
                if len(pairs) < 2:
                    continue  # jednoliniowy wpis obsługuje ścieżka fragmentów
                if filter_untranslated and _is_mostly_untranslated(db_source, db_target):
                    continue
                signature = "|".join(p[1] for p in pairs)
                if signature in seen_line_pairs:
                    continue
                seen_line_pairs.add(signature)
                assembled = _replace_flat_span(haystack, flat, flat_to_orig, db_flat, db_target)
                coverage = int(round(len(db_flat) * 100 / max(len(flat), 1)))
                line_matches.append(
                    SentenceMatch(db_source, db_target, assembled or haystack, coverage,
                                  line_pairs=pairs, kind="linia")
                )

        # 1c) relacja ODWROTNA: segment jest KRÓTSZY niż wpis TM.
        #     Typowe, gdy segmentacja rozbiła zdanie po \n, a TM trzyma całość
        #     ("GIFT System." wobec wpisu "Thank you ... MYSTERY\nGIFT System.").
        #     Wtedy pokazujemy tę linię wpisu, która odpowiada segmentowi.
        if not hits and flat:
            seen_sub: set[str] = set()
            for i in scan:
                db_source = self._index.sources[i]
                db_flat = self._index.flats[i]
                if len(db_flat) <= len(flat) or flat not in db_flat:
                    continue
                db_target = self._index.targets[i]
                if db_target in seen_sub:
                    continue
                if filter_untranslated and _is_mostly_untranslated(db_source, db_target):
                    continue
                pairs = align_lines(db_source, db_target)
                # wybierz linię wpisu, która najlepiej odpowiada segmentowi
                best_line: Optional[Tuple[str, str]] = None
                for src_line, tgt_line in pairs:
                    if _flatten_text(src_line) == flat:
                        best_line = (src_line, tgt_line)
                        break
                if best_line is None:
                    for src_line, tgt_line in pairs:
                        if flat in _flatten_text(src_line):
                            best_line = (src_line, tgt_line)
                            break
                seen_sub.add(db_target)
                coverage = int(round(len(flat) * 100 / max(len(db_flat), 1)))
                if best_line is not None:
                    line_matches.append(
                        SentenceMatch(best_line[0], best_line[1], best_line[1], coverage,
                                      line_pairs=pairs, kind="linia z dłuższego wpisu")
                    )
                else:
                    line_matches.append(
                        SentenceMatch(db_source, db_target, db_target, coverage,
                                      line_pairs=pairs, kind="segment w dłuższym wpisie")
                    )
                if len(line_matches) >= limit:
                    break

        # 1d) DOPASOWANIE ROZMYTE LINIA PO LINII – najważniejszy przypadek w praktyce.
        #     Wpis TM rzadko jest dokładnym podciągiem segmentu: bywa inne słowo
        #     ("accessing" zamiast "using") albo znacznik końca (<<KON>>). Dlatego
        #     każdą linię segmentu porównujemy rozmyto z liniami wpisów TM.
        line_matches.extend(
            self._fuzzy_line_matches(segment, filter_untranslated, should_cancel)
        )

        if not hits and not line_matches:
            return []

        found: List[SentenceMatch] = []
        for start, end, db_source, db_target in hits:
            assembled = haystack[:start] + db_target + haystack[end:]
            coverage = int(round((end - start) * 100 / max(len(haystack), 1)))
            found.append(SentenceMatch(db_source, db_target, assembled, coverage))
        found.sort(key=lambda m: -m.coverage)

        # 2) złożenie zbiorcze: podstaw naraz wszystkie fragmenty, które się nie
        #    nakładają (najdłuższe mają pierwszeństwo) – to zwykle najlepsza propozycja
        if len(hits) > 1:
            chosen: List[Tuple[int, int, str, str]] = []
            for hit in sorted(hits, key=lambda h: -(h[1] - h[0])):
                if all(hit[1] <= c[0] or hit[0] >= c[1] for c in chosen):
                    chosen.append(hit)
            if len(chosen) > 1:
                combined = haystack
                covered = 0
                for start, end, _src, tgt in sorted(chosen, key=lambda h: -h[0]):
                    combined = combined[:start] + tgt + combined[end:]
                    covered += end - start
                coverage = int(round(covered * 100 / max(len(haystack), 1)))
                found.insert(
                    0,
                    SentenceMatch(
                        " + ".join(c[2] for c in sorted(chosen, key=lambda h: h[0])),
                        " + ".join(c[3] for c in sorted(chosen, key=lambda h: h[0])),
                        combined,
                        coverage,
                        kind="złożenie",
                    ),
                )

        # Propozycje, które zostawiają w wyniku surowy angielski, są dla
        # tłumacza pułapką: wyglądają jak gotowe zdanie, a podmieniają samą
        # końcówkę („Would you like to mix records with\nINNE TRAINERS?”).
        # Oznaczamy je i spychamy na koniec listy.
        # Kolejność wyników: najpierw te z gotowym złożeniem CAŁEGO segmentu
        # (dokładne trafienia), potem podpowiedzi pojedynczych linii.
        if line_matches:
            exact_line = [m for m in line_matches if not m.kind.startswith("linia ~")]
            fuzzy_line = [m for m in line_matches if m.kind.startswith("linia ~")]
            exact_line.sort(key=lambda m: -m.coverage)
            fuzzy_line.sort(key=lambda m: -m.coverage)
            found = exact_line + found + fuzzy_line

        # Propozycje, które zostawiają w wyniku surowy angielski, są dla
        # tłumacza pułapką: wyglądają jak gotowe zdanie, a podmieniają samą
        # końcówkę („Would you like to mix records with\nINNE TRAINERS?”).
        # Oznaczamy je i spychamy na koniec listy — bez usuwania, bo bywają
        # użyteczne jako podpowiedź terminu.
        for match in found:
            match.partial = _leaves_source_text(segment, match.assembled)
        found.sort(key=lambda m: (m.partial, -m.coverage))

        return found[:limit]

    def _fuzzy_line_matches(self, segment: str, filter_untranslated: bool,
                            should_cancel: Optional[Callable[[], bool]] = None) -> List[SentenceMatch]:
        """Dla każdej linii segmentu szuka najlepszej linii w pamięci TM.

        Segment jest dzielony po ``\\n`` / ``\\p``; każdy kawałek porównujemy
        z liniami wpisów TM (rozbitymi tak samo). Dzięki temu podpowiedź działa
        także wtedy, gdy wpis w pamięci różni się słowem lub ma dodatkowy
        znacznik końca – czyli w sytuacji, w której zwykłe szukanie podciągu zawodzi.
        """
        threshold = SettingsManager.instance().get_int("tm.sentence.line.threshold", 65)
        # porównujemy CAŁE zdania, nie urwane linie (patrz split_units_for_matching)
        seg_lines = split_units_for_matching(segment)
        if not seg_lines:
            return []

        # Cache linii budujemy PRZYROSTOWO: dopisujemy tylko wpisy, których
        # jeszcze nie przetworzyliśmy. Pełna przebudowa przy każdym segmencie
        # była głównym powodem długiego oczekiwania.
        # Cache budujemy PORCJAMI, zwalniając blokadę i oddając GIL między nimi.
        # Wcześniej całość szła pod jedną blokadą, przez co wątek interfejsu
        # czekał nawet kilkaset ms i okno wyraźnie „muliło”.
        CHUNK = 512
        while True:
            with self._lock:
                total = len(self._index)
                if self._line_cache_size > total:   # np. po wyczyszczeniu pamięci
                    self._line_keys, self._line_src, self._line_tgt = [], [], []
                    self._line_cache_size = 0
                start_at = max(self._line_cache_size, 0)
                if start_at >= total:
                    keys = self._line_keys
                    srcs = self._line_src
                    tgts = self._line_tgt
                    break
                stop_at = min(start_at + CHUNK, total)
                for i in range(start_at, stop_at):
                    db_source = self._index.sources[i]
                    db_target = self._index.targets[i]
                    # 1) CAŁY wpis – pozwala dopasować pełne zdanie segmentu
                    #    do pełnego tłumaczenia (a nie tylko do jednej linii).
                    flat_whole = self._index.flats[i]
                    if len(flat_whole) >= 4:
                        self._line_keys.append(flat_whole)
                        self._line_src.append(db_source)
                        self._line_tgt.append(db_target)
                    # 2) poszczególne linie – gdy pamięć ma krótsze wpisy
                    pairs = align_lines(db_source, db_target)
                    if len(pairs) > 1:
                        for src_line, tgt_line in pairs:
                            flat_line = _flatten_text(src_line)
                            if len(flat_line) >= 4:
                                self._line_keys.append(flat_line)
                                self._line_src.append(src_line)
                                self._line_tgt.append(tgt_line)
                self._line_cache_size = stop_at
            # poza blokadą: pozwól interfejsowi działać
            if should_cancel is not None and should_cancel():
                return []
            time.sleep(0)

        if not keys:
            return []

        results: List[SentenceMatch] = []
        seen: set[str] = set()

        # Wszystkie linie segmentu porównujemy JEDNYM wywołaniem `cdist`,
        # które liczy macierz podobieństw na wielu rdzeniach i – co ważniejsze –
        # zwalnia GIL na czas obliczeń. Wcześniej każda linia szła osobno
        # w pętli Pythona, co blokowało interfejs.
        if should_cancel is not None and should_cancel():
            return results
        flat_lines = [(sl, _flatten_text(sl)) for sl in seg_lines]
        flat_lines = [(sl, fl) for sl, fl in flat_lines if len(fl) >= 4]
        if not flat_lines:
            return results

        best_per_line: List[Tuple[int, int]] = []   # (wynik, indeks w cache)
        if HAS_RAPIDFUZZ:
            queries = [fl for _sl, fl in flat_lines]
            rough_cut = max(30, threshold - 35)
            try:
                matrix = _rf_process.cdist(
                    queries, keys, scorer=_rf_fuzz.ratio,
                    score_cutoff=rough_cut, workers=-1,
                )
            except TypeError:       # starsze rapidfuzz bez `workers`
                matrix = _rf_process.cdist(
                    queries, keys, scorer=_rf_fuzz.ratio, score_cutoff=rough_cut
                )
            for row_no, (_sl, flat_seg) in enumerate(flat_lines):
                if should_cancel is not None and should_cancel():
                    return results
                row = matrix[row_no]
                # Kilkunastu najlepszych kandydatów ocenia dokładne WRatio.
                # `argpartition` wybiera je bez sortowania całej macierzy –
                # sortowanie 40 tys. elementów w Pythonie kosztowało więcej
                # niż samo porównywanie.
                k = 25
                if HAS_NUMPY:
                    if row.size > k:
                        part = _np.argpartition(row, -k)[-k:]
                        top = [int(i) for i in part if row[i] > 0]
                    else:
                        top = [int(i) for i in range(row.size) if row[i] > 0]
                else:
                    top = sorted(range(len(row)), key=lambda i: -row[i])[:k]
                    top = [i for i in top if row[i] > 0]
                best_score, best_idx = 0, -1
                seg_words = set(_TOKEN_RE.findall(flat_seg))
                for i in top:
                    cand = keys[i]
                    # Wymóg pokrycia SŁÓW: krótki wpis („System”) nie może
                    # uchodzić za dopasowanie całej linii („GIFT System.”)
                    # tylko dlatego, że WRatio wysoko ocenia dopasowanie częściowe.
                    if seg_words:
                        covered = len(seg_words & set(_TOKEN_RE.findall(cand)))
                        if covered / len(seg_words) < _MIN_LINE_WORD_COVERAGE:
                            continue
                    score = _rf_fuzz.WRatio(flat_seg, cand)
                    if score >= threshold and score > best_score:
                        best_score, best_idx = int(round(score)), i
                best_per_line.append((best_score, best_idx))
        else:
            cutoff = threshold / 100.0
            for _sl, flat_seg in flat_lines:
                if should_cancel is not None and should_cancel():
                    return results
                best_score, best_idx = 0, -1
                n = len(flat_seg)
                seg_words = set(_TOKEN_RE.findall(flat_seg))
                for i, key in enumerate(keys):
                    if seg_words:
                        covered = len(seg_words & set(_TOKEN_RE.findall(key)))
                        if covered / len(seg_words) < _MIN_LINE_WORD_COVERAGE:
                            continue
                    short, long = (flat_seg, key) if n <= len(key) else (key, flat_seg)
                    ratio = SequenceMatcher(None, short, long).ratio()
                    if len(short) < len(long):
                        best_local = ratio
                        step = max(1, len(short) // 2)
                        for st in range(0, len(long) - len(short) + 1, step):
                            best_local = max(
                                best_local,
                                SequenceMatcher(None, short, long[st:st + len(short)]).ratio(),
                            )
                        ratio = best_local
                    score = ratio * 100
                    if score >= threshold and score > best_score:
                        best_score, best_idx = int(round(score)), i
                best_per_line.append((best_score, best_idx))

        for (seg_line, _flat), (best_score, best_idx) in zip(flat_lines, best_per_line):
            if best_idx < 0:
                continue

            src_line, tgt_line = srcs[best_idx], tgts[best_idx]
            if filter_untranslated and _is_mostly_untranslated(src_line, tgt_line):
                continue
            signature = f"{seg_line}\x00{tgt_line}"
            if signature in seen:
                continue
            seen.add(signature)
            # Złożenie = CAŁY segment z podstawioną linią. Wcześniej wstawiało
            # się samo tłumaczenie linii, przez co „całość” gubiła resztę tekstu.
            assembled = _replace_line_in_segment(segment, seg_line, tgt_line)
            coverage = int(round(len(seg_line) * 100 / max(len(segment), 1)))
            # Gdy dopasowaliśmy wpis wielolinijkowy, pokaż też rozbicie
            # linia po linii – łatwiej wtedy przenieść tłumaczenie kawałkami.
            pairs = align_lines(src_line, tgt_line)
            if len(pairs) > 1:
                # wpis TM ma kilka linii – pokaż je jedna pod drugą.
                # Jeśli segment dzieli się tak samo, sparuj po kolei;
                # w przeciwnym razie pokaż linie tak, jak są w pamięci.
                seg_parts = split_lines_by_codes(seg_line)
                if len(seg_parts) == len(pairs):
                    line_pairs = [(seg_parts[i], pairs[i][1]) for i in range(len(pairs))]
                else:
                    line_pairs = list(pairs)
            else:
                line_pairs = [(seg_line, tgt_line)]
            results.append(
                SentenceMatch(
                    src_line, tgt_line, assembled, coverage,
                    line_pairs=line_pairs,
                    kind=f"fragment ~{best_score}%",
                )
            )
        return results

    # ------------------------------------------------------------------
    def import_tmx(self, path: str, progress: Optional[Callable[[int], None]] = None) -> int:
        """Importuje plik TMX. Zwraca liczbę zaimportowanych jednostek."""
        if not self._conn:
            raise RuntimeError("Pamięć TM nie została zainicjalizowana (otwórz projekt).")

        rows: List[Tuple[str, str, str, str]] = []
        # iterparse => stały narzut pamięci nawet przy plikach na setki MB
        context = ET.iterparse(path, events=("end",))
        count = 0
        for _event, elem in context:
            if not elem.tag.endswith("tu"):
                continue
            source_text = target_text = None
            source_lang, target_lang = "en", "pl"
            for tuv in list(elem):
                if not tuv.tag.endswith("tuv"):
                    continue
                lang = (
                    tuv.get("{http://www.w3.org/XML/1998/namespace}lang") or tuv.get("lang") or ""
                )
                seg = next((c for c in tuv if c.tag.endswith("seg")), None)
                if seg is None:
                    continue
                text = "".join(seg.itertext()).strip()
                if source_text is None:
                    source_text, source_lang = text, lang
                elif target_text is None:
                    target_text, target_lang = text, lang
            if source_text and target_text:
                rows.append((source_text, target_text, source_lang or "en", target_lang or "pl"))
            count += 1
            if progress and count % 500 == 0:
                progress(min(99, count // 100))
            elem.clear()

        imported = 0
        chunk = 2000
        for i in range(0, len(rows), chunk):
            self.add_many(rows[i:i + chunk])
            imported += len(rows[i:i + chunk])
            if progress:
                progress(int(min(99, (i + chunk) * 100 / max(len(rows), 1))))
        self._dirty = True
        if progress:
            progress(100)
        return imported

    def export_tmx(self, path: str, source_lang: str = "en", target_lang: str = "pl") -> int:
        """Eksportuje całą TM do pliku TMX 1.4."""
        self.flush()
        entries = [(src, tgt, sl, tl) for src, tgt, sl, tl, _uc in self.all_entries()]
        return write_tmx(path, entries, source_lang, target_lang)

    def auto_import_folder(self, folder: str) -> int:
        """Importuje pliki .tmx z folderu tm/, pomijając już wczytane.

        Stan każdego pliku (rozmiar + czas modyfikacji) zapisujemy w tabeli
        `tm_files`. Dzięki temu przy kolejnym otwarciu projektu niezmienione
        pamięci nie są importowane po raz drugi – wcześniej cała zawartość
        przechodziła przez bazę przy każdym starcie.
        """
        if not os.path.isdir(folder) or not self._conn:
            return 0
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS tm_files ("
            " path TEXT PRIMARY KEY, size INTEGER, mtime REAL, units INTEGER)"
        )
        self._conn.commit()
        known = {
            row[0]: (row[1], row[2])
            for row in self._conn.execute("SELECT path, size, mtime FROM tm_files")
        }

        imported = 0
        for name in sorted(os.listdir(folder)):
            if not name.lower().endswith(".tmx"):
                continue
            path = os.path.join(folder, name)
            try:
                stat = os.stat(path)
                stamp = (stat.st_size, stat.st_mtime)
                if known.get(os.path.abspath(path)) == stamp:
                    continue  # plik już wczytany i niezmieniony
                count = self.import_tmx(path)
                imported += count
                self._conn.execute(
                    "INSERT OR REPLACE INTO tm_files (path, size, mtime, units) VALUES (?, ?, ?, ?)",
                    (os.path.abspath(path), stat.st_size, stat.st_mtime, count),
                )
                self._conn.commit()
            except Exception as exc:
                print(f"⚠️ Błąd importu {name}: {exc}")
        return imported

    def imported_files(self) -> List[Tuple[str, int]]:
        """Zwraca listę wczytanych plików TMX: (ścieżka, liczba jednostek)."""
        if not self._conn:
            return []
        try:
            return [(row[0], row[1]) for row in
                    self._conn.execute("SELECT path, units FROM tm_files ORDER BY path")]
        except sqlite3.Error:
            return []

    def stats(self) -> dict:
        if not self._conn:
            return {"total": 0, "pairs": {}, "top": []}
        pairs: dict = {}
        for row in self._conn.execute(
            "SELECT source_lang, target_lang, COUNT(*) FROM translation_memory GROUP BY source_lang, target_lang"
        ):
            pairs[f"{row[0] or '?'} → {row[1] or '?'}"] = row[2]
        top = list(
            self._conn.execute(
                "SELECT source_text, usage_count FROM translation_memory ORDER BY usage_count DESC LIMIT 5"
            )
        )
        return {"total": self.size(), "pairs": pairs, "top": top}


def _flatten_text(text: str) -> str:
    """Tekst do porównań: bez znaczników linii, bez akcentów, małe litery."""
    return _strip_accents(unify_control_codes(text or "").lower())


#: Podział tekstu na linie po znacznikach \n \p \l \r \c oraz prawdziwych przełamach.
_LINE_SPLIT_RE = re.compile(r"(?:\\[npNPlLrRcC]|\r\n|\r|\n)")


def split_lines_by_codes(text: str) -> List[str]:
    """Dzieli tekst na linie po znacznikach ``\\n`` / ``\\p`` i prawdziwych przełamach.

    W plikach gier jeden wpis TM często obejmuje kilka wyświetlanych linii,
    np. ``Thank you for using the MYSTERY\\nGIFT System.`` To pozwala dopasować
    i pokazać je linia po linii.
    """
    if not text:
        return []
    return [part.strip() for part in _LINE_SPLIT_RE.split(text) if part and part.strip()]


def split_units_for_matching(text: str) -> List[str]:
    """Dzieli segment na jednostki do porównania z pamięcią.

    Zamiast ciąć po każdym ``\n`` (co daje urwane kawałki w rodzaju
    „Thank you for using the STAMP CARD” albo samo „System.”), scalamy linie
    aż do znaku kończącego zdanie. Dzięki temu porównujemy pełne myśli,
    a nie fragmenty pozbawione sensu.

    Zwraca zarówno całe zdania, jak i pojedyncze linie — te drugie przydają się,
    gdy pamięć zawiera wpisy złożone dokładnie z jednej linii.
    """
    lines = split_lines_by_codes(text)
    if not lines:
        return []

    sentences: List[str] = []
    buffer: List[str] = []
    for line in lines:
        buffer.append(line)
        if line.rstrip().endswith((".", "!", "?", ":", "…", "”", '"')):
            sentences.append(" ".join(buffer).strip())
            buffer = []
    if buffer:
        sentences.append(" ".join(buffer).strip())

    units: List[str] = []
    seen: set[str] = set()
    for candidate in sentences + lines:
        key = candidate.strip().lower()
        # pomiń urywki bez treści (np. samo „System.”, jeśli jest już w zdaniu)
        if not key or key in seen or len(candidate.strip()) < 4:
            continue
        seen.add(key)
        units.append(candidate.strip())
    return units


def align_lines(source_text: str, target_text: str) -> List[Tuple[str, str]]:
    """Paruje linie tekstu źródłowego z liniami tłumaczenia.

    Gdy liczba linii jest równa – parowanie jest jeden do jednego. Gdy się różni,
    nadmiarowe linie są doklejane do ostatniej pary, aby nic nie zginęło.
    """
    src_lines = split_lines_by_codes(source_text)
    tgt_lines = split_lines_by_codes(target_text)
    if not src_lines or not tgt_lines:
        return []
    if len(src_lines) == len(tgt_lines):
        return list(zip(src_lines, tgt_lines))
    pairs: List[Tuple[str, str]] = []
    common = min(len(src_lines), len(tgt_lines))
    for i in range(common - 1):
        pairs.append((src_lines[i], tgt_lines[i]))
    pairs.append((" ".join(src_lines[common - 1:]), " ".join(tgt_lines[common - 1:])))
    return pairs


def _replace_line_in_segment(segment: str, line: str, replacement: str) -> str:
    """Podstawia tłumaczenie fragmentu, zachowując resztę segmentu i znaczniki.

    Fragment bywa **scalonym zdaniem** (np. ``the STAMP CARD System.``), które
    w oryginale jest przełamane znacznikiem (``the STAMP CARD\nSystem.``).
    Dlatego przy nieudanym dopasowaniu dosłownym szukamy po tekście
    „spłaszczonym” i odtwarzamy zakres w oryginale.
    """
    if not line:
        return segment
    for needle in (line, line.strip()):
        idx = segment.find(needle)
        if idx >= 0:
            return segment[:idx] + replacement + segment[idx + len(needle):]

    # dopasowanie po treści – z pominięciem \n, \p i różnic w spacjach
    flat_segment, mapping = _flatten_with_map(segment)
    flat_line = _flatten_text(line)
    if flat_line:
        replaced = _replace_flat_span(segment, flat_segment, mapping, flat_line, replacement)
        if replaced is not None:
            return replaced
    return segment


def _replace_flat_span(original: str, flat: str, flat_to_orig: List[int],
                       needle_flat: str, replacement: str) -> Optional[str]:
    """Podmienia w oryginale fragment odnaleziony w tekście spłaszczonym."""
    if not needle_flat:
        return None
    start = flat.find(needle_flat)
    if start < 0:
        return None
    end_index = start + len(needle_flat) - 1
    if end_index >= len(flat_to_orig):
        return None
    orig_start = flat_to_orig[start]
    orig_end = flat_to_orig[end_index] + 1
    return original[:orig_start] + replacement + original[orig_end:]


def _flatten_with_map(text: str) -> Tuple[str, List[int]]:
    """Zwraca (tekst spłaszczony, mapowanie pozycji na indeksy w oryginale).

    Znaczniki ``\\n``/``\\p`` i białe znaki są zwijane do pojedynczej spacji,
    a mapa pozwala odtworzyć zakres w oryginalnym napisie.
    """
    flat_chars: List[str] = []
    mapping: List[int] = []
    i, n = 0, len(text)
    pending_space = False
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n and text[i + 1] in "npNPlLrRcC":
            pending_space = True
            i += 2
            continue
        if ch in " \t\r\n":
            pending_space = True
            i += 1
            continue
        if pending_space and flat_chars:
            flat_chars.append(" ")
            mapping.append(i)
        pending_space = False
        flat_chars.append(_strip_accents(ch.lower()) or ch.lower())
        mapping.append(i)
        i += 1
    # _strip_accents może zwrócić pusty napis dla znaków łączących – wyrównaj długości
    flat = "".join(flat_chars)
    if len(flat) != len(mapping):  # pragma: no cover - zabezpieczenie
        flat, mapping = flat[: len(mapping)], mapping[: len(flat)]
    return flat, mapping


#: Do ilu wyrazów wpis identyczny po obu stronach uznajemy za świadomy wybór
#: tłumacza (nazwa własna, etykieta), a nie za pracę niedokończoną.
_IDENTICAL_WORD_LIMIT = 4


def _leaves_source_text(segment: str, assembled: str) -> bool:
    """Czy w złożonej propozycji został kawałek tekstu źródłowego.

    Dopasowanie zdań podmienia w segmencie tylko znaleziony fragment. Gdy
    fragment jest krótki, reszta zdania zostaje **po angielsku** — taka
    propozycja bywa gorsza niż jej brak, bo łatwo ją zatwierdzić przez pomyłkę.
    Porównujemy wyrazy: jeśli w wyniku przetrwała większość słów oryginału,
    uznajemy złożenie za niepełne.
    """
    if not segment or not assembled:
        return False
    source_words = [w for w in _TOKEN_RE.findall(segment.lower()) if len(w) > 2]
    if not source_words:
        return False
    result_words = set(_TOKEN_RE.findall(assembled.lower()))
    kept = sum(1 for w in source_words if w in result_words)
    return kept / len(source_words) > 0.5


def _is_mostly_untranslated(source: str, target: str) -> bool:
    """Wykrywa wpisy TM, gdzie 'tłumaczenie' to praktycznie kopia źródła.

    **Uwaga na nazwy własne.** W plikach gier mnóstwo wpisów jest z założenia
    identycznych po obu stronach: ``CINNABAR GYM``, ``PP UP``, ``TM01 FOCUS
    PUNCH``, okrzyki (``POLIWRATH: Ribi ribit!``). To są **poprawne, świadome
    tłumaczenia** — tłumacz zdecydował zostawić oryginalną nazwę. Wcześniej
    filtr odrzucał je wszystkie, więc „Zastosuj TM” zostawiało takie segmenty
    puste, mimo że pamięć miała trafienie 100%.

    Dlatego odrzucamy tylko wpisy, które naprawdę wyglądają na **niedokończoną
    pracę**: dłuższe zdania skopiowane bez zmian. Krótkie hasła i wpisy pisane
    wersalikami (typowe dla nazw w grach) przepuszczamy.
    """
    if not source or not target:
        return False

    identical = source.strip().lower() == target.strip().lower()
    words = _TOKEN_RE.findall(target)
    if identical:
        # Długi tekst identyczny po obu stronach to niedokończona praca
        # („Thank you for using the MYSTERY GIFT System.” → to samo).
        if len(words) > _IDENTICAL_WORD_LIMIT:
            return True
        # Krótki wpis z NAZWĄ WŁASNĄ (wersaliki: CINNABAR GYM, PP UP,
        # TM01 FOCUS PUNCH, POLIWRATH) to świadomy wybór tłumacza — zostaje.
        if any(len(w) >= 2 and w.isupper() for w in words):
            return False
        # Krótki wpis bez nazwy własnej („System.” → „System.”) niczego nie
        # wnosi i tylko zaśmieca podpowiedzi jako „dopasowanie 100%”.
        return True

    s_words = set(_TOKEN_RE.findall(source.lower()))
    t_words = set(_TOKEN_RE.findall(target.lower()))
    if not t_words:
        return False
    if len(t_words) <= _IDENTICAL_WORD_LIMIT:
        return False        # zbyt krótkie, by wyrokować – lepiej pokazać wpis

    return len(s_words & t_words) / len(t_words) > 0.9


def _xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _xml_attr(text: str) -> str:
    return _xml_escape(text).replace('"', "&quot;")
