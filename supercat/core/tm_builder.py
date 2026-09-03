"""Budowanie pamięci TM z par plików dwujęzycznych.

Typowy przypadek: masz ten sam tekst w dwóch plikach — `text_en.txt`
(angielski) i `text_pl.txt` (polski) — gdzie **wiersz N odpowiada wierszowi N**.
Ten moduł zestawia takie pliki w pary i zamienia je na wpisy pamięci TM.

Moduł jest niezależny od Qt, żeby dało się go testować bez interfejsu.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

#: Rozszerzenia, z których umiemy czytać wiersze tekstu.
TEXT_EXTENSIONS = (".txt", ".inc", ".po", ".csv", ".tsv", ".md", ".srt", ".lang", ".ini")

#: Kodowania sprawdzane po kolei, gdy plik nie jest w UTF-8.
#: `cp1250` i `iso-8859-2` to typowe kodowania polskich plików z Windows.
FALLBACK_ENCODINGS = ("utf-8-sig", "utf-8", "cp1250", "iso-8859-2", "cp1252", "latin-1")

#: Znaczniki końca wypowiedzi w plikach gier – nie są tekstem do tłumaczenia.
_TECHNICAL_LINE_RE = re.compile(
    r"""^\s*(
        <<<\s*FILE:.*>>>        # <<< FILE: miasto/text.inc >>>
        | \#.*                  # komentarz
        | //.*                  # komentarz
        | \[[^\]]+\]            # [sekcja]
        | -{3,}                 # ---- separator
        | ={3,}
    )\s*$""",
    re.VERBOSE,
)

#: Wzorce nazw wskazujące język pliku: text_en.txt, en/text.txt, text.en.txt
#: Wyrazy (litery Unicode) – do rozpoznawania języka wiersza.
_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)

_LANG_IN_NAME_RE = re.compile(
    r"(?:^|[._\-\s])(?P<code>[a-z]{2}(?:[_-][a-z]{2})?)(?:[._\-\s]|$)", re.IGNORECASE)


def detect_encoding(path: str) -> str:
    """Rozpoznaje kodowanie pliku tekstowego.

    Pliki gier i eksporty z Windows bywają w `cp1250` albo `ISO-8859-2`.
    Czytanie ich jako UTF-8 kończy się wyjątkiem albo krzakami zamiast
    polskich znaków, więc sprawdzamy kodowania po kolei i wybieramy
    pierwsze, które odczyta plik bez błędu.
    """
    try:
        with open(path, "rb") as handle:
            head = handle.read(1_000_000)
    except OSError:
        return "utf-8"
    if head.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    for encoding in FALLBACK_ENCODINGS:
        try:
            head.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
        return encoding
    return "utf-8"


def read_lines(path: str, encoding: str = "") -> List[str]:
    """Wczytuje wiersze pliku, zachowując puste (numeracja musi się zgadzać)."""
    used = encoding or detect_encoding(path)
    with open(path, "r", encoding=used, errors="replace", newline="") as handle:
        text = handle.read()
    # Ujednolicamy końce wierszy – plik z Windows nie może dawać innego
    # podziału niż ten sam plik zapisany na Linuksie.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()          # ostatni znak nowej linii nie tworzy wiersza
    return lines


def language_hint(path: str) -> str:
    """Zgaduje kod języka z nazwy pliku lub katalogu (``text_en.txt`` → ``en``).

    Zwraca pusty napis, gdy nic pewnego nie da się odczytać.
    """
    known = {"en", "pl", "de", "fr", "es", "it", "nl", "cs", "ru", "uk", "pt",
             "sv", "zh", "ja", "ko", "tr", "hu", "ro", "sk", "da", "fi", "no",
             "el", "bg", "he", "ar", "hi", "id", "vi", "th", "ca", "eu", "ga"}
    name = os.path.splitext(os.path.basename(path))[0]
    for match in _LANG_IN_NAME_RE.finditer(name):
        code = match.group("code").lower().replace("-", "_")
        if code in known:
            return code
        if code.split("_")[0] in known:
            return code.split("_")[0]
    folder = os.path.basename(os.path.dirname(path)).lower()
    if folder in known:
        return folder
    return ""


def _strip_language(path: str) -> str:
    """Nazwa pliku bez znacznika języka – klucz do parowania plików."""
    name = os.path.splitext(os.path.basename(path))[0]
    code = language_hint(path)
    if code:
        for pattern in (rf"[._\-]{code}$", rf"^{code}[._\-]", rf"[._\-]{code}[._\-]"):
            new = re.sub(pattern, lambda m: "" if m.group(0)[-1] not in "._-"
                         else m.group(0)[-1], name, flags=re.IGNORECASE)
            if new != name:
                return new.strip("._- ").lower()
    return name.strip("._- ").lower()


def plural_lines(count: int) -> str:
    """Polska odmiana: 1 wiersz, 2 wiersze, 5 wierszy."""
    if count == 1:
        return "1 wiersz"
    last, last_two = count % 10, count % 100
    if 2 <= last <= 4 and not 12 <= last_two <= 14:
        return f"{count} wiersze"
    return f"{count} wierszy"


#: Nazwa kodowania „wykryj automatycznie” pokazywana w interfejsie.
AUTO_ENCODING = "auto"

#: Kodowania do wyboru w interfejsie (pierwsze = automatyczne).
ENCODING_CHOICES = [
    (AUTO_ENCODING, "wykryj automatycznie"),
    ("utf-8", "UTF-8"),
    ("utf-8-sig", "UTF-8 ze znacznikiem BOM"),
    ("cp1250", "Windows-1250 (środkowoeuropejskie)"),
    ("iso-8859-2", "ISO-8859-2 (Latin-2)"),
    ("cp1252", "Windows-1252 (zachodnie)"),
    ("iso-8859-1", "ISO-8859-1 (Latin-1)"),
    ("cp1251", "Windows-1251 (cyrylica)"),
    ("shift_jis", "Shift-JIS (japoński)"),
    ("euc-kr", "EUC-KR (koreański)"),
    ("gbk", "GBK (chiński)"),
    ("utf-16", "UTF-16"),
]


@dataclass
class FilePair:
    """Para plików: źródłowy i docelowy, wraz z wynikiem sprawdzenia.

    Nazwy plików mogą być **dowolne** (`1.txt` + `2.txt`), a język i kodowanie
    każdej strony da się ustawić ręcznie — automatyczne rozpoznanie jest tylko
    podpowiedzią, nie wymogiem.
    """

    source_path: str
    target_path: str
    source_lines: int = 0
    target_lines: int = 0
    source_lang: str = ""
    target_lang: str = ""
    source_encoding: str = AUTO_ENCODING
    target_encoding: str = AUTO_ENCODING

    def encoding_of(self, side: str) -> str:
        """Kodowanie użyte do odczytu danej strony (`source` / `target`)."""
        chosen = (self.source_encoding if side == "source"
                  else self.target_encoding)
        if chosen and chosen != AUTO_ENCODING:
            return chosen
        return detect_encoding(self.source_path if side == "source"
                               else self.target_path)

    def lines(self, side: str) -> List[str]:
        """Wiersze wskazanej strony, z uwzględnieniem wybranego kodowania."""
        path = self.source_path if side == "source" else self.target_path
        return read_lines(path, self.encoding_of(side))

    def recount(self) -> None:
        """Przelicza wiersze — po zmianie kodowania liczba może się zmienić."""
        self.source_lines = len(self.lines("source"))
        self.target_lines = len(self.lines("target"))

    @property
    def name(self) -> str:
        return os.path.basename(self.source_path)

    @property
    def matches(self) -> bool:
        """Czy liczba wierszy się zgadza (warunek poprawnego zestawienia)."""
        return self.source_lines == self.target_lines and self.source_lines > 0

    @property
    def status(self) -> str:
        if self.source_lines == 0 or self.target_lines == 0:
            return "pusty plik"
        if self.matches:
            return f"✅ {plural_lines(self.source_lines)}"
        difference = abs(self.source_lines - self.target_lines)
        return (f"❌ różnica {plural_lines(difference)} "
                f"({self.source_lines} / {self.target_lines})")


def pair_files(paths: Sequence[str], source_lang: str = "",
               target_lang: str = "") -> Tuple[List[FilePair], List[str]]:
    """Zestawia pliki w pary źródło–tłumaczenie.

    Kolejność prób:

    1. **Po nazwie z kodem języka** — ``text_en.txt`` + ``text_pl.txt``.
    2. **Po dowolnych nazwach**, gdy plików jest dokładnie dwa
       (``1.txt`` + ``2.txt``) albo gdy zostaje parzysta reszta — łączymy
       je parami w kolejności alfabetycznej.

    Nazwa pliku **nie jest wymogiem** — to tylko podpowiedź. Języki i tak
    można potem zmienić ręcznie dla każdej pary.
    """
    files = [p for p in paths if os.path.isfile(p)]
    pairs: List[FilePair] = []
    used: set = set()

    def make_pair(first: str, second: str) -> FilePair:
        first_lang = language_hint(first)
        second_lang = language_hint(second)
        # Gdy nazwy zdradzają język, ustawiamy kierunek zgodnie z projektem.
        if source_lang and second_lang == source_lang.lower():
            first, second = second, first
            first_lang, second_lang = second_lang, first_lang
        elif target_lang and first_lang == target_lang.lower():
            first, second = second, first
            first_lang, second_lang = second_lang, first_lang
        pair = FilePair(
            source_path=first, target_path=second,
            source_lang=first_lang or source_lang,
            target_lang=second_lang or target_lang,
        )
        pair.recount()
        return pair

    # 1) pary rozpoznane po kodzie języka w nazwie
    groups: Dict[str, List[str]] = {}
    for path in files:
        if language_hint(path):
            groups.setdefault(_strip_language(path), []).append(path)
    for _key, members in sorted(groups.items()):
        if len(members) == 2:
            pairs.append(make_pair(*sorted(members)))
            used.update(members)

    # 2) reszta – parujemy po kolejności, bo nazwy nic nie mówią.
    #    Nie łączymy jednak plików o TYM SAMYM języku (np. dwa pliki z katalogu
    #    `en/`): to na pewno nie jest para źródło–tłumaczenie, a taka „para”
    #    dawała bezsensowne wpisy TM (angielski → angielski).
    rest = sorted(p for p in files if p not in used)
    unmatched: List[str] = []
    while len(rest) >= 2:
        first = rest.pop(0)
        first_lang = language_hint(first)
        partner_at = None
        for position, candidate in enumerate(rest):
            other_lang = language_hint(candidate)
            if first_lang and other_lang and first_lang == other_lang:
                continue          # ten sam język – szukamy dalej
            partner_at = position
            break
        if partner_at is None:
            unmatched.append(first)     # został sam wśród plików w swoim języku
            continue
        pairs.append(make_pair(first, rest.pop(partner_at)))
    unmatched.extend(rest)          # ewentualny nieparzysty plik
    return pairs, sorted(unmatched)


@dataclass
class BuildOptions:
    """Ustawienia zestawiania – co pomijać przy tworzeniu wpisów TM."""

    skip_empty: bool = True             # pomiń wiersze puste po obu stronach
    skip_identical: bool = False        # pomiń wiersze identyczne (nieprzetłumaczone)
    skip_technical: bool = True         # pomiń <<< FILE: … >>>, komentarze, [sekcje]
    trim: bool = True                   # przytnij spacje na brzegach
    require_equal_lines: bool = True    # nie zestawiaj plików o różnej liczbie wierszy
    min_length: int = 1                 # najkrótszy akceptowany tekst źródłowy
    #: Pomija wiersze, w których „tłumaczenie” zostało w języku źródłowym.
    skip_untranslated: bool = False


@dataclass
class BuildResult:
    """Wynik zestawiania: gotowe wpisy i licznik pominięć."""

    rows: List[Tuple[str, str, str, str]] = field(default_factory=list)
    skipped_empty: int = 0
    skipped_identical: int = 0
    skipped_technical: int = 0
    skipped_short: int = 0
    skipped_half: int = 0               # tekst tylko po jednej stronie
    skipped_untranslated: int = 0       # „tłumaczenie” wciąż po angielsku
    problems: List[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.rows)

    @property
    def skipped(self) -> int:
        return (self.skipped_empty + self.skipped_identical + self.skipped_technical
                + self.skipped_short + self.skipped_half + self.skipped_untranslated)

    def summary(self) -> str:
        """Podsumowanie po ludzku – trafia do okna wyniku."""
        parts = [f"Gotowych par: {self.total}"]
        if self.skipped_empty:
            parts.append(f"puste: {self.skipped_empty}")
        if self.skipped_half:
            parts.append(f"brak odpowiednika: {self.skipped_half}")
        if self.skipped_technical:
            parts.append(f"wiersze techniczne: {self.skipped_technical}")
        if self.skipped_identical:
            parts.append(f"identyczne: {self.skipped_identical}")
        if self.skipped_short:
            parts.append(f"za krótkie: {self.skipped_short}")
        if self.skipped_untranslated:
            parts.append(f"nieprzetłumaczone: {self.skipped_untranslated}")
        return "  •  ".join(parts)


#: Wyrazy typowe wyłącznie dla polszczyzny – szybki test „czy to już polski”.
_POLISH_MARKERS = frozenset("""
 jest sie się nie tak czy oraz albo lecz ale gdy jeśli aby żeby który która które
 tego temu tym tych tej tą ten ta to co za do od na po we ze przez dla bez pod nad
 masz mam ma masz jesteś jestem możesz mogę chcesz chcę będzie były był była
 wszystko coś nic ktoś nikt bardzo już jeszcze tylko także również więc dlatego
 dziękuję proszę przepraszam witaj cześć tutaj teraz zawsze nigdy kiedy gdzie
""".split())

#: Wyrazy typowe dla angielskiego – po nich poznajemy tekst nieprzetłumaczony.
_ENGLISH_MARKERS = frozenset("""
 the and you your are was were will would can could should have has had this that
 these those with from for into about your yours they them their there here what
 when where which who whom how why not but out get got give take make made want
 like need know think see look come back time please thank sorry hello
""".split())

#: Litery występujące wyłącznie w polskim alfabecie.
_POLISH_LETTERS = frozenset("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")


def looks_polish(text: str) -> bool:
    """Czy tekst wygląda na polski (litery diakrytyczne albo typowe wyrazy)."""
    if not text:
        return False
    if _POLISH_LETTERS & set(text):
        return True
    words = {w.lower() for w in _WORD_RE.findall(text)}
    return bool(words & _POLISH_MARKERS)


def looks_english(text: str) -> bool:
    """Czy tekst wygląda na angielski (typowe wyrazy funkcyjne)."""
    if not text:
        return False
    words = {w.lower() for w in _WORD_RE.findall(text)}
    return bool(words & _ENGLISH_MARKERS)


def is_untranslated(source: str, target: str) -> bool:
    """Czy „tłumaczenie” w rzeczywistości pozostało w języku źródłowym.

    Wykrywa dwa przypadki, które zaśmiecają pamięć TM:

    * tłumaczenie **identyczne** ze źródłem (poza krótkimi nazwami własnymi —
      ``PP UP``, ``CINNABAR GYM`` — które tłumacz zostawia świadomie),
    * tłumaczenie **wciąż po angielsku**: ma typowe angielskie wyrazy
      funkcyjne i ani jednego znaku polskiego.

    Nazwy własne pisane wersalikami nie są tu brane pod uwagę, bo w plikach
    gier występują po obu stronach (``other TRAINERS`` → ``inni TRENERZY``).
    """
    if not source or not target:
        return False
    source_clean, target_clean = source.strip(), target.strip()
    if not source_clean or not target_clean:
        return False

    if source_clean.lower() == target_clean.lower():
        words = _WORD_RE.findall(target_clean)
        if len(words) <= 4 and any(len(w) >= 2 and w.isupper() for w in words):
            return False        # krótka nazwa własna – zostawiona celowo
        return True

    # Tłumaczenie po polsku – w porządku, nawet jeśli zawiera angielskie nazwy.
    if looks_polish(target_clean):
        return False
    # Brak cech polskich, a widać angielskie słowa funkcyjne → nieprzetłumaczone.
    return looks_english(target_clean)


def is_technical_line(text: str) -> bool:
    """Czy wiersz to nagłówek/komentarz, a nie tekst do tłumaczenia."""
    return bool(_TECHNICAL_LINE_RE.match(text))


def build_pairs(pairs: Sequence[FilePair], source_lang: str, target_lang: str,
                options: Optional[BuildOptions] = None,
                on_progress: Optional[Callable[[int, int, str], None]] = None
                ) -> BuildResult:
    """Zamienia pary plików na wpisy pamięci TM.

    Zestawianie idzie **wiersz po wierszu**: wiersz N pliku źródłowego trafia
    do pamięci razem z wierszem N pliku docelowego. Dlatego liczba wierszy musi
    się zgadzać — inaczej całe tłumaczenie przesunęłoby się o jeden i pamięć
    byłaby bezużyteczna.
    """
    options = options or BuildOptions()
    result = BuildResult()
    seen: set = set()

    for index, pair in enumerate(pairs):
        if on_progress is not None:
            on_progress(index, len(pairs), pair.name)
        if options.require_equal_lines and not pair.matches:
            result.problems.append(
                f"{pair.name}: pominięto — {pair.status}")
            continue

        source_lines = pair.lines("source")
        target_lines = pair.lines("target")
        limit = min(len(source_lines), len(target_lines))

        for row in range(limit):
            source = source_lines[row]
            target = target_lines[row]
            if options.trim:
                source, target = source.strip(), target.strip()

            if not source and not target:
                result.skipped_empty += 1
                continue
            if not source or not target:
                # Jedna strona pusta — para nie niesie tłumaczenia.
                result.skipped_half += 1
                continue
            if options.skip_technical and (is_technical_line(source)
                                           or is_technical_line(target)):
                result.skipped_technical += 1
                continue
            if options.skip_identical and source == target:
                result.skipped_identical += 1
                continue
            if len(source) < max(1, options.min_length):
                result.skipped_short += 1
                continue
            if options.skip_untranslated and is_untranslated(source, target):
                result.skipped_untranslated += 1
                continue

            key = (source, target)
            if key in seen:
                continue              # duplikat w obrębie tego zestawu
            seen.add(key)
            result.rows.append((
                source, target,
                pair.source_lang or source_lang,
                pair.target_lang or target_lang,
            ))

    if on_progress is not None:
        on_progress(len(pairs), len(pairs), "")
    return result


#: Powody pominięcia wiersza – pokazywane w podglądzie zestawienia.
SKIP_REASONS = {
    "": "",
    "empty": "pusty wiersz",
    "half": "tekst tylko po jednej stronie",
    "technical": "wiersz techniczny",
    "identical": "identyczne po obu stronach",
    "short": "za krótkie",
    "untranslated": "nieprzetłumaczone (wciąż po angielsku)",
}


def classify_line(source: str, target: str,
                  options: Optional[BuildOptions] = None) -> str:
    """Zwraca powód pominięcia wiersza albo pusty napis, gdy wiersz wchodzi do TM.

    Ta sama logika, co w `build_pairs` — dzięki temu podgląd pokazuje
    dokładnie to, co program naprawdę zrobi.
    """
    options = options or BuildOptions()
    if options.trim:
        source, target = source.strip(), target.strip()
    if not source and not target:
        return "empty"
    if not source or not target:
        return "half"
    if options.skip_technical and (is_technical_line(source)
                                   or is_technical_line(target)):
        return "technical"
    if options.skip_identical and source == target:
        return "identical"
    if len(source) < max(1, options.min_length):
        return "short"
    if options.skip_untranslated and is_untranslated(source, target):
        return "untranslated"
    return ""


def preview_alignment(pair: FilePair, limit: int = 30,
                      options: Optional[BuildOptions] = None,
                      show_skipped: bool = False
                      ) -> List[Tuple[int, str, str, str]]:
    """Zestawione wiersze do podglądu — z powodem pominięcia.

    Zwraca krotki ``(numer, źródło, tłumaczenie, powód)``. Pusty powód znaczy,
    że wiersz trafi do pamięci. Przy `show_skipped=True` lista zawiera także
    wiersze pomijane (puste, techniczne, nieprzetłumaczone) — widać wtedy
    **dlaczego** dany wiersz nie wejdzie do TM, zamiast zgadywać z liczników.
    """
    options = options or BuildOptions()
    source_lines = pair.lines("source")
    target_lines = pair.lines("target")
    rows: List[Tuple[int, str, str, str]] = []
    for index in range(min(len(source_lines), len(target_lines))):
        source = source_lines[index]
        target = target_lines[index]
        if options.trim:
            source, target = source.strip(), target.strip()
        reason = classify_line(source, target, options)
        if reason and not show_skipped:
            continue
        rows.append((index + 1, source, target, reason))
        if len(rows) >= limit:
            break
    return rows
