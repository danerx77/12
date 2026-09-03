"""Kontrola poprawności języka polskiego — TYLKO w tłumaczeniu.

Dwa niezależne poziomy:

1. **Reguły offline** (zawsze dostępne, bez internetu) — typowe błędy interpunkcji,
   spacji, powtórzeń, oraz odmiany po liczebnikach i przyimkach. Napisane pod
   teksty gier: nie zgłaszają znaczników ``\\n``, ``\\p``, ``<<KON>>`` ani zmiennych
   ``{STR_VAR_1}``.
2. **LanguageTool** (opcjonalny, przez internet) — pełna kontrola gramatyki,
   odmiany i pisowni. Publiczne API ``api.languagetool.org`` działa bez klucza
   (limit ok. 20 zapytań/min); można też wskazać własny serwer.

Moduł jest niezależny od GUI, żeby dało się go testować bez Qt.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

LT_PUBLIC_URL = "https://api.languagetool.org/v2/check"
#: Poniżej tylu wyrazów słownik uznajemy za niepełny i pomijamy kontrolę pisowni.
MIN_DICTIONARY_FOR_SPELLCHECK = 5000
LT_LANGUAGE = "pl-PL"

SEVERITY_ERROR = "błąd"
SEVERITY_WARNING = "ostrzeżenie"
SEVERITY_INFO = "info"


@dataclass
class LangIssue:
    """Pojedyncza uwaga językowa dotycząca tłumaczenia."""

    category: str
    message: str
    severity: str = SEVERITY_WARNING
    fragment: str = ""
    suggestions: List[str] = field(default_factory=list)
    offset: int = -1
    length: int = 0
    rule_id: str = ""
    source: str = "offline"      # offline | languagetool

    def describe(self) -> str:
        out = self.message
        if self.fragment:
            out += f"  →  „{self.fragment}”"
        if self.suggestions:
            out += "  •  propozycje: " + ", ".join(self.suggestions[:3])
        return out


# --------------------------------------------------------------- znaczniki
#: Znaczniki plików gier i zmienne – wycinamy je przed kontrolą języka,
#: żeby LanguageTool nie zgłaszał ich jako błędów pisowni.
CODE_PATTERN = re.compile(r"\\[a-zA-Z]|<<[^<>]{1,24}>>|\{[A-Za-z0-9_]{1,32}\}|\[[A-Za-z0-9_]{1,24}\]")


def mask_codes(text: str, filler: str = " ") -> Tuple[str, List[Tuple[int, int]]]:
    """Zastępuje znaczniki neutralnym wypełniaczem tej samej długości.

    Zachowanie długości jest istotne: dzięki temu przesunięcia (``offset``)
    zwrócone przez LanguageTool wskazują właściwe miejsce w ORYGINALNYM tekście.

    Wypełniaczem jest SPACJA, a nie litera: ``z\\nSystemu`` musi rozpaść się na
    „z” i „Systemu”, a nie skleić w nieistniejący wyraz „zXXSystemu”.
    """
    if not text:
        return "", []
    spans: List[Tuple[int, int]] = []
    out = []
    last = 0
    for match in CODE_PATTERN.finditer(text):
        out.append(text[last:match.start()])
        out.append(filler * (match.end() - match.start()))
        spans.append((match.start(), match.end()))
        last = match.end()
    out.append(text[last:])
    return "".join(out), spans


def _in_spans(offset: int, length: int, spans: Sequence[Tuple[int, int]]) -> bool:
    end = offset + max(1, length)
    return any(offset < s_end and s_start < end for s_start, s_end in spans)


# ------------------------------------------------------------ reguły offline
#: Liczebniki wymagające dopełniacza liczby mnogiej (pięć jabłek, nie „pięć jabłko”).
_GENITIVE_NUMERALS = {
    "pięć", "sześć", "siedem", "osiem", "dziewięć", "dziesięć", "jedenaście",
    "dwanaście", "trzynaście", "czternaście", "piętnaście", "szesnaście",
    "siedemnaście", "osiemnaście", "dziewiętnaście", "dwadzieścia", "trzydzieści",
    "czterdzieści", "pięćdziesiąt", "sześćdziesiąt", "siedemdziesiąt",
    "osiemdziesiąt", "dziewięćdziesiąt", "sto", "dwieście", "trzysta", "czterysta",
    "pięćset", "sześćset", "siedemset", "osiemset", "dziewięćset", "tysiąc",
}
#: Liczebniki wymagające mianownika liczby mnogiej (dwa koty, trzy psy).
_NOMINATIVE_PLURAL_NUMERALS = {"dwa", "dwie", "trzy", "cztery", "oba", "obie"}

#: Częste literówki i kalki w tłumaczeniach na polski.
_COMMON_MISTAKES: List[Tuple[re.Pattern, str, str]] = [
    (re.compile(r"\bnaprzeciwko\s+do\b", re.I), "naprzeciwko + dopełniacz", "„naprzeciwko czegoś”, bez „do”"),
    (re.compile(r"\bwedług\s+mnie\s+uważam\b", re.I), "pleonazm", "wystarczy „uważam” albo „według mnie”"),
    (re.compile(r"\bw\s+każdym\s+bądź\s+razie\b", re.I), "błędny zwrot", "poprawnie: „w każdym razie” lub „bądź co bądź”"),
    (re.compile(r"\bpo\s+za\s+tym\b", re.I), "pisownia łączna", "poprawnie: „poza tym”"),
    (re.compile(r"\bna\s+prawdę\b", re.I), "pisownia łączna", "poprawnie: „naprawdę”"),
    (re.compile(r"\bw\s+ogóle\s+nie\s+ma\s+żadnego\b", re.I), "podwójne przeczenie", "uprość zdanie"),
    (re.compile(r"\bcofać\s+się\s+do\s+tyłu\b", re.I), "pleonazm", "wystarczy „cofać się”"),
    (re.compile(r"\bkontynuować\s+dalej\b", re.I), "pleonazm", "wystarczy „kontynuować”"),
    (re.compile(r"\bokres\s+czasu\b", re.I), "pleonazm", "wystarczy „okres” albo „czas”"),
    (re.compile(r"\bfakt\s+autentyczny\b", re.I), "pleonazm", "wystarczy „fakt”"),
    (re.compile(r"\bdwoje\s+drzwi\b", re.I), "", ""),   # poprawne – nie zgłaszamy
    (re.compile(r"\btą\s+(?:książkę|drogę|rzecz|kartę|grę)\b", re.I),
     "biernik rodzaju żeńskiego", "w bierniku: „tę książkę”, nie „tą”"),
    (re.compile(r"\bwziąść\b", re.I), "błędna forma", "poprawnie: „wziąć”"),
    (re.compile(r"\bwłanczać\b|\bwłanczam\b|\bwyłanczać\b", re.I), "błędna forma",
     "poprawnie: „włączać”, „wyłączać”"),
    (re.compile(r"\bposzłem\b", re.I), "błędna forma", "poprawnie: „poszedłem”"),
    (re.compile(r"\bumiem\s+to\s+zrobić\s+potrafię\b", re.I), "powtórzenie", ""),
    (re.compile(r"\bswoją\s+drogą\s+swoją\b", re.I), "powtórzenie", ""),
    (re.compile(r"\bbardziej\s+lepszy\b|\bbardziej\s+lepsze\b", re.I),
     "podwójny stopień wyższy", "wystarczy „lepszy”"),
    (re.compile(r"\bnajbardziej\s+najlepszy\b", re.I), "podwójny stopień najwyższy", "wystarczy „najlepszy”"),
]

#: Zaimki osobowe i pasujące do nich końcówki czasownika w czasie przeszłym.
_PRONOUN_ENDINGS = {
    "ja": ("m", "łem", "łam"),
    "ty": ("ś", "łeś", "łaś"),
    "my": ("śmy", "liśmy", "łyśmy"),
    "wy": ("ście", "liście", "łyście"),
}

_SENTENCE_END = ".!?…"
_TOKEN_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def _check_punctuation(text: str) -> List[LangIssue]:
    issues: List[LangIssue] = []

    # spacja PRZED znakiem interpunkcyjnym
    for match in re.finditer(r"\s+([,.;:!?])", text):
        issues.append(LangIssue(
            "Interpunkcja", "Spacja przed znakiem interpunkcyjnym",
            SEVERITY_WARNING, match.group(0).strip() or match.group(1),
            [match.group(1)], match.start(), len(match.group(0)),
            "SPACJA_PRZED_ZNAKIEM",
        ))

    # brak spacji PO przecinku / średniku (pomijamy liczby: 1,5 oraz znaczniki)
    for match in re.finditer(r"[,;](?=[^\s\d\\])", text):
        issues.append(LangIssue(
            "Interpunkcja", "Brak spacji po znaku interpunkcyjnym",
            SEVERITY_WARNING, text[max(0, match.start() - 6):match.start() + 6],
            [], match.start(), 1, "BRAK_SPACJI_PO_ZNAKU",
        ))

    # podwojone znaki (poza wielokropkiem i „?!”)
    for match in re.finditer(r"([,.;:!?])\1+", text):
        if match.group(0) in ("...", "!!", "??"):
            continue
        issues.append(LangIssue(
            "Interpunkcja", "Powtórzony znak interpunkcyjny",
            SEVERITY_INFO, match.group(0), [match.group(1)],
            match.start(), len(match.group(0)), "POWTORZONY_ZNAK",
        ))

    # niesparowane nawiasy i cudzysłowy
    if text.count("(") != text.count(")"):
        issues.append(LangIssue("Interpunkcja", "Niesparowane nawiasy okrągłe",
                                SEVERITY_WARNING, "", [], -1, 0, "NAWIASY"))
    if text.count("„") != text.count("”"):
        issues.append(LangIssue("Interpunkcja", "Niesparowane cudzysłowy „ ”",
                                SEVERITY_INFO, "", [], -1, 0, "CUDZYSLOWY"))

    # spacja przed znakiem końca zdania na końcu tekstu
    for match in re.finditer(r"\s+$", text):
        if text.strip():
            break
    return issues


def _check_spacing(text: str) -> List[LangIssue]:
    issues: List[LangIssue] = []
    # podwójna spacja WEWNĄTRZ tekstu (wcięcia na brzegach są zamierzone)
    for match in re.finditer(r"\S([ \t]{2,})\S", text):
        issues.append(LangIssue(
            "Białe znaki", "Podwójna spacja w środku tekstu",
            SEVERITY_INFO, match.group(0), [" "], match.start() + 1,
            len(match.group(1)), "PODWOJNA_SPACJA",
        ))
    return issues


def _check_repeats(text: str) -> List[LangIssue]:
    """Powtórzony wyraz obok siebie: „to to jest”."""
    issues: List[LangIssue] = []
    # 2 znaki wystarczą („to to”, „że że”); przecinek między wyrazami rozdziela
    # poprawne konstrukcje typu „To, to jest…”, więc \s+ ich nie złapie.
    for match in re.finditer(r"\b([^\W\d_]{2,})\s+\1\b", text, re.IGNORECASE | re.UNICODE):
        issues.append(LangIssue(
            "Powtórzenia", f"Powtórzony wyraz „{match.group(1)}”",
            SEVERITY_WARNING, match.group(0), [match.group(1)],
            match.start(), len(match.group(0)), "POWTORZONY_WYRAZ",
        ))
    return issues


def _check_capitalization(text: str) -> List[LangIssue]:
    """Mała litera po kropce kończącej zdanie."""
    issues: List[LangIssue] = []
    for match in re.finditer(r"[.!?]\s+([a-ząćęłńóśźż])", text):
        before = text[:match.start()]
        # skróty typu „np.”, „itd.” nie kończą zdania
        last_word = re.search(r"([^\W\d_]+)\.$", before + ".")
        if last_word and last_word.group(1).lower() in {"np", "itd", "itp", "tzn", "tzw", "ok", "m", "in"}:
            continue
        issues.append(LangIssue(
            "Wielkość liter", "Mała litera po kropce",
            SEVERITY_WARNING, text[match.start():match.end() + 8],
            [match.group(1).upper()], match.end() - 1, 1, "MALA_PO_KROPCE",
        ))
    return issues


def _check_numerals(text: str) -> List[LangIssue]:
    """Odmiana rzeczownika po liczebniku (pięć jabłek, nie „pięć jabłko”)."""
    issues: List[LangIssue] = []
    words = list(re.finditer(r"[^\W\d_]+", text, re.UNICODE))
    for i, match in enumerate(words[:-1]):
        word = match.group(0).lower()
        nxt = words[i + 1]
        noun = nxt.group(0)
        if len(noun) < 4:
            continue
        low = noun.lower()
        if word in _GENITIVE_NUMERALS:
            # dopełniacz l.mn. rzadko kończy się na -o/-a/-ę (jabłko, gruszka, kartę)
            if low.endswith(("o", "ę")) or (low.endswith("a") and not low.endswith("ia")):
                issues.append(LangIssue(
                    "Odmiana", f"Po liczebniku „{match.group(0)}” oczekiwany dopełniacz liczby mnogiej",
                    SEVERITY_WARNING, f"{match.group(0)} {noun}", [],
                    nxt.start(), len(noun), "LICZEBNIK_DOPELNIACZ",
                ))
        elif word in _NOMINATIVE_PLURAL_NUMERALS:
            if low.endswith(("ów", "ach", "om", "ami")):
                issues.append(LangIssue(
                    "Odmiana", f"Po liczebniku „{match.group(0)}” oczekiwany mianownik liczby mnogiej",
                    SEVERITY_WARNING, f"{match.group(0)} {noun}", [],
                    nxt.start(), len(noun), "LICZEBNIK_MIANOWNIK",
                ))
    return issues


def _check_pronoun_agreement(text: str) -> List[LangIssue]:
    """Zgodność zaimka z czasownikiem: „ja poszedł” → „ja poszedłem”."""
    issues: List[LangIssue] = []
    for pronoun, endings in _PRONOUN_ENDINGS.items():
        pattern = re.compile(rf"\b{pronoun}\s+([^\W\d_]+ł[aeoiy]?)\b", re.IGNORECASE | re.UNICODE)
        for match in pattern.finditer(text):
            verb = match.group(1).lower()
            if verb.endswith(endings):
                continue
            issues.append(LangIssue(
                "Odmiana", f"Czasownik nie zgadza się z zaimkiem „{pronoun}”",
                SEVERITY_WARNING, match.group(0), [],
                match.start(), len(match.group(0)), "ZAIMEK_CZASOWNIK",
            ))
    return issues


def _check_common_mistakes(text: str) -> List[LangIssue]:
    issues: List[LangIssue] = []
    for pattern, label, hint in _COMMON_MISTAKES:
        if not label:
            continue
        for match in pattern.finditer(text):
            issues.append(LangIssue(
                "Poprawność", f"{label}: „{match.group(0).strip()}”",
                SEVERITY_WARNING, match.group(0).strip(),
                [hint] if hint else [], match.start(), len(match.group(0)),
                "TYPOWY_BLAD",
            ))
    return issues


def check_offline(text: str, dictionary=None, options: Optional[dict] = None) -> List[LangIssue]:
    """Kontrola bez internetu: interpunkcja, spacje, odmiana, typowe błędy.

    ``dictionary`` – opcjonalny obiekt ``Dictionary``; gdy podany, dokłada
    kontrolę pisowni na podstawie wczytanych słowników.
    ``options`` – słownik przełączników (patrz `default_options`); pozwala
    wyłączyć poszczególne rodzaje kontroli w Ustawieniach.
    """
    if not text or not text.strip():
        return []
    opts = default_options()
    if options:
        opts.update(options)
    if not opts.get("enabled", True):
        return []

    masked, spans = mask_codes(text)

    active = []
    if opts.get("punctuation", True):
        active += [_check_punctuation, _check_spacing, _check_repeats, _check_capitalization]
    if opts.get("grammar", True):
        active += [_check_numerals, _check_pronoun_agreement, _check_common_mistakes]

    issues: List[LangIssue] = []
    for check in active:
        for issue in check(masked):
            if issue.offset >= 0 and _in_spans(issue.offset, issue.length, spans):
                continue    # trafienie wewnątrz znacznika – pomijamy
            if issue.offset >= 0:
                issue.fragment = text[max(0, issue.offset):issue.offset + max(issue.length, 1)] or issue.fragment
            issues.append(issue)

    # Kontrola pisowni ma sens dopiero przy pełnym słowniku. Przy liście kilkuset
    # wyrazów niemal każde słowo byłoby „spoza słownika” – panel zalałby szum.
    if (opts.get("spelling", True)
            and dictionary is not None and getattr(dictionary, "is_initialized", False)
            and getattr(dictionary, "size", 0) >= MIN_DICTIONARY_FOR_SPELLCHECK):
        skip_caps = opts.get("skip_uppercase", True)
        try:
            unknown = dictionary.check_text(masked, skip_uppercase=skip_caps)
        except TypeError:               # starsza sygnatura bez przełącznika
            unknown = dictionary.check_text(masked)
        # UWAGA: sugestii NIE liczymy tutaj. Hunspell potrzebuje ok. 1 s na wyraz,
        # więc dla pięciu literówek panel czekałby 5 s. Podkreślenia mają pojawić
        # się natychmiast; propozycje dolicza się na żądanie – przy otwarciu menu
        # podręcznego albo w tle (`fill_suggestions`).
        for word in unknown[:20]:
            suggestions: List[str] = []
            # pozycja wyrazu w tekście – potrzebna do podkreślenia w edytorze
            found = re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text)
            offset = found.start() if found else -1
            length = len(word) if found else 0
            issues.append(LangIssue(
                # Pisownia to BŁĄD, nie „info” – w edytorach tekstu literówka
                # dostaje czerwoną falkę i tak samo ma być tutaj.
                "Pisownia", f"Słowo spoza słownika: „{word}”",
                SEVERITY_ERROR, word, suggestions, offset, length, "PISOWNIA",
            ))

    issues.sort(key=lambda i: (i.offset if i.offset >= 0 else 10 ** 6, i.category))
    return issues


# --------------------------------------------------- LanguageTool offline
class LocalLanguageTool:
    """LanguageTool uruchomiony NA KOMPUTERZE – działa bez internetu.

    Wymaga pakietu ``language-tool-python`` i Javy. Przy pierwszym uruchomieniu
    biblioteka pobiera silnik (~230 MB) i zapisuje go w katalogu domowym;
    kolejne starty trwają ok. 2 s. Sprawdzenie zdania to potem 70–150 ms,
    bez limitów zapytań i bez wysyłania tekstu w internet.
    """

    #: Wspólna instancja – uruchamianie serwera dla każdego sprawdzenia
    #: kosztowałoby kilka sekund.
    _shared: Optional["LocalLanguageTool"] = None

    def __init__(self, language: str = LT_LANGUAGE, version: str = "") -> None:
        self.language = language or LT_LANGUAGE
        self.version = version
        self._tool = None
        self.last_error = ""

    @classmethod
    def instance(cls, language: str = LT_LANGUAGE, version: str = "") -> "LocalLanguageTool":
        if cls._shared is None or cls._shared.language != language:
            cls.shutdown()
            cls._shared = cls(language, version)
        return cls._shared

    @classmethod
    def shutdown(cls) -> None:
        """Zatrzymuje lokalny serwer (wywoływane przy zamykaniu programu)."""
        if cls._shared is not None:
            cls._shared.close()
            cls._shared = None

    # ------------------------------------------------------- wykrywanie Javy
    #: Katalogi, w których typowo lądują instalacje Javy (poza PATH).
    _JAVA_SEARCH_GLOBS = [
        # Windows
        r"C:\Program Files\Java\*\bin\java.exe",
        r"C:\Program Files\Eclipse Adoptium\*\bin\java.exe",
        r"C:\Program Files\Microsoft\jdk*\bin\java.exe",
        r"C:\Program Files\Amazon Corretto\*\bin\java.exe",
        r"C:\Program Files\BellSoft\*\bin\java.exe",
        r"C:\Program Files\Zulu\*\bin\java.exe",
        r"C:\Program Files\JetBrains\*\jbr\bin\java.exe",
        r"C:\Program Files (x86)\Java\*\bin\java.exe",
        # Linux
        "/usr/lib/jvm/*/bin/java",
        "/opt/java/*/bin/java",
        "/opt/jdk*/bin/java",
        # macOS
        "/Library/Java/JavaVirtualMachines/*/Contents/Home/bin/java",
    ]

    @staticmethod
    def java_version(java_path: str) -> Tuple[int, int]:
        """Zwraca (główna, poboczna) wersję Javy spod podanej ścieżki.

        Obsługuje oba zapisy: „1.8.0_401” (stary) oraz „17.0.9” / „26” (nowy).
        Zwraca (0, 0), gdy nie da się ustalić.
        """
        import subprocess

        try:
            output = subprocess.run(
                [java_path, "-version"], capture_output=True, text=True, timeout=15,
            )
        except Exception:
            return 0, 0
        text = (output.stderr or "") + (output.stdout or "")
        match = re.search(r'version "?(\d+)(?:\.(\d+))?', text)
        if not match:
            match = re.search(r"\b(?:openjdk|java)\s+(\d+)(?:\.(\d+))?", text, re.I)
        if not match:
            return 0, 0
        major = int(match.group(1))
        minor = int(match.group(2) or 0)
        if major == 1:          # zapis 1.8 = Java 8
            return minor, 0
        return major, minor

    @staticmethod
    def find_java_installations() -> List[Tuple[str, int]]:
        """Szuka wszystkich Java na komputerze. Zwraca [(ścieżka, wersja główna)].

        Biblioteka LanguageTool bierze pod uwagę wyłącznie ``which("java")``,
        więc gdy w PATH została stara Java 8, nowszy JDK nie zostanie użyty.
        Tutaj przeglądamy też ``JAVA_HOME`` i typowe katalogi instalacyjne.
        """
        import glob
        import os
        import shutil

        found: Dict[str, int] = {}

        def consider(path: Optional[str]) -> None:
            if not path or not os.path.isfile(path):
                return
            real = os.path.realpath(path)
            if real in found:
                return
            major, _minor = LocalLanguageTool.java_version(path)
            if major:
                found[real] = major

        java_home = os.environ.get("JAVA_HOME", "")
        if java_home:
            for name in ("java.exe", "java"):
                consider(os.path.join(java_home, "bin", name))
        consider(shutil.which("java"))
        for pattern in LocalLanguageTool._JAVA_SEARCH_GLOBS:
            for path in glob.glob(pattern):
                consider(path)

        return sorted(found.items(), key=lambda item: -item[1])

    @staticmethod
    def best_java() -> Tuple[str, int]:
        """Najnowsza znaleziona Java: (ścieżka, wersja). ("", 0) gdy brak."""
        override = ""
        try:
            from .settings import SettingsManager

            override = SettingsManager.instance().get("lang.check.java.path", "") or ""
        except Exception:
            pass
        if override:
            major, _minor = LocalLanguageTool.java_version(override)
            if major:
                return override, major

        installations = LocalLanguageTool.find_java_installations()
        return installations[0] if installations else ("", 0)

    @staticmethod
    def prepare_java_env() -> Tuple[str, int]:
        """Ustawia PATH tak, aby biblioteka znalazła NAJNOWSZĄ Javę.

        Bez tego `which("java")` zwróciłby starą wersję z PATH (np. 1.8),
        mimo że na dysku jest nowszy JDK.
        """
        import os

        path, major = LocalLanguageTool.best_java()
        if not path:
            return "", 0
        bin_dir = os.path.dirname(path)
        current = os.environ.get("PATH", "")
        if bin_dir and bin_dir not in current.split(os.pathsep)[:1]:
            os.environ["PATH"] = bin_dir + os.pathsep + current
        os.environ.setdefault("JAVA_HOME", os.path.dirname(bin_dir))
        return path, major

    @staticmethod
    def required_lt_version(java_major: int) -> str:
        """Dobiera wersję LanguageTool do posiadanej Javy.

        LT 6.x wymaga Javy 17+, LT 5.9 wystarczy Java 9+.
        Poniżej Javy 9 nie zadziała żadna wersja.
        """
        if java_major >= 17:
            return ""          # domyślna (najnowsza)
        if java_major >= 9:
            return "5.9"
        return "brak"

    @staticmethod
    def install_dir() -> str:
        """Katalog, w którym biblioteka trzyma pobrany silnik."""
        try:
            from language_tool_python.utils import LTP_PATH  # type: ignore

            return str(LTP_PATH)
        except Exception:
            import os

            return os.path.join(os.path.expanduser("~"), ".cache", "language_tool_python")

    @staticmethod
    def is_downloaded() -> bool:
        """Czy silnik jest już pobrany na dysk (nie trzeba czekać na 230 MB)."""
        import os

        folder = LocalLanguageTool.install_dir()
        if not os.path.isdir(folder):
            return False
        for name in os.listdir(folder):
            if name.startswith("LanguageTool") and os.path.isdir(os.path.join(folder, name)):
                return True
        return False

    @staticmethod
    def installed_size_mb() -> float:
        """Rozmiar pobranego silnika w MB (0, gdy go nie ma)."""
        import os

        folder = LocalLanguageTool.install_dir()
        if not os.path.isdir(folder):
            return 0.0
        total = 0
        for root, _dirs, files in os.walk(folder):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    continue
        return total / 1024 / 1024

    @staticmethod
    def remove_engine() -> bool:
        """Usuwa pobrany silnik z dysku (zwalnia ~500 MB)."""
        import os
        import shutil

        LocalLanguageTool.shutdown()
        folder = LocalLanguageTool.install_dir()
        if not os.path.isdir(folder):
            return False
        removed = False
        for name in os.listdir(folder):
            path = os.path.join(folder, name)
            if name.startswith("LanguageTool") and os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
                removed = True
        return removed

    @staticmethod
    def _patch_progress(on_progress) -> Optional[Callable[[], None]]:
        """Podstawia własny licznik postępu zamiast paska `tqdm` biblioteki.

        `language_tool_python` pobiera archiwum sam i pokazuje postęp przez
        `tqdm` w konsoli. Podmieniamy tę klasę na własną, która przekazuje
        (pobrane, całość) do interfejsu — dzięki temu widać prawdziwe procenty,
        a nie „migający” pasek. Zwraca funkcję przywracającą oryginał.
        """
        try:
            from language_tool_python import download_lt as _dl
        except Exception:
            return None

        original = getattr(_dl, "tqdm", None)
        if original is None:
            return None

        class _ProgressProxy:
            """Udaje obiekt tqdm: przyjmuje `total` i zlicza `update()`."""

            def __init__(self, *args, **kwargs):
                self.total = kwargs.get("total") or 0
                self.n = 0
                on_progress(0, self.total)

            def update(self, amount=1):
                self.n += amount or 0
                on_progress(self.n, self.total)

            def close(self):
                on_progress(self.n, self.total or self.n)

            def set_description(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.close()
                return False

        class _FakeModule:
            tqdm = _ProgressProxy

            def __getattr__(self, name):
                return getattr(original, name)

        _dl.tqdm = _FakeModule()

        def restore() -> None:
            _dl.tqdm = original

        return restore

    @staticmethod
    def download_engine(version: str = "", on_progress=None) -> Tuple[bool, str]:
        """Pobiera silnik LanguageTool na dysk. Zwraca (sukces, komunikat).

        ``on_progress(pobrane_bajty, wszystkie_bajty)`` – wywoływane w trakcie
        transferu; `wszystkie_bajty` wynosi 0, gdy serwer nie poda rozmiaru.
        Wywoływane z osobnego wątku – transfer to ok. 230 MB.
        """
        ok, message = LocalLanguageTool.is_available()
        if not ok:
            return False, message
        _java_path, java_major = LocalLanguageTool.prepare_java_env()
        chosen = version or LocalLanguageTool.required_lt_version(java_major)
        if chosen == "brak":
            return False, (f"Java {java_major} jest za stara dla LanguageTool. "
                           "Zainstaluj Javę 17 lub nowszą (adoptium.net).")
        restore = LocalLanguageTool._patch_progress(on_progress) if on_progress else None
        try:
            import language_tool_python

            kwargs = {"language_tool_download_version": chosen} if chosen else {}
            tool = language_tool_python.LanguageTool("pl-PL", **kwargs)
            tool.close()
            return True, ""
        except Exception as exc:
            text = str(exc)
            if "Java" in text and ">=" in text and not version:
                # Zapas: starsze wydanie silnika działa jeszcze z Javą 9+.
                return LocalLanguageTool.download_engine("5.9", on_progress)
            return False, text
        finally:
            if restore is not None:
                restore()

    @staticmethod
    def is_available() -> Tuple[bool, str]:
        """Sprawdza, czy da się uruchomić LanguageTool lokalnie."""
        try:
            import language_tool_python  # noqa: F401
        except ImportError:
            return False, ("Brak pakietu „language-tool-python”. "
                           "Zainstaluj: pip install language-tool-python")

        path, major = LocalLanguageTool.best_java()
        if not path:
            return False, ("Nie znaleziono Javy. LanguageTool offline wymaga Javy 17 "
                           "lub nowszej (adoptium.net albo pakiet „default-jre”).")
        if major < 9:
            return False, (f"Znaleziona Java {major} jest za stara — potrzebna Java 17 "
                           f"(albo co najmniej 9 dla starszego silnika).\n{path}")
        return True, ""

    @staticmethod
    def java_report() -> str:
        """Czytelny opis znalezionych instalacji Javy (do Ustawień)."""
        installations = LocalLanguageTool.find_java_installations()
        if not installations:
            return "❌ Nie znaleziono Javy na tym komputerze."
        best_path, best_major = installations[0]
        lines = [f"✅ Używana Java: {best_major}  ({best_path})"]
        if len(installations) > 1:
            others = ", ".join(f"{major} ({path})" for path, major in installations[1:4])
            lines.append(f"Pozostałe znalezione: {others}")
        needed = LocalLanguageTool.required_lt_version(best_major)
        if needed == "brak":
            lines.append("⚠️ Ta wersja jest za stara — zainstaluj Javę 17 lub nowszą.")
        elif needed:
            lines.append(f"ℹ️ Dla tej Javy zostanie użyty LanguageTool {needed} "
                         f"(najnowszy wymaga Javy 17).")
        return "\n".join(lines)

    def start(self) -> bool:
        """Uruchamia serwer. Zwraca True, gdy gotowy do pracy."""
        if self._tool is not None:
            return True
        ok, message = self.is_available()
        if not ok:
            self.last_error = message
            return False
        # Najpierw wskaż bibliotece najnowszą Javę z komputera – sama zajrzy
        # tylko do PATH, gdzie może siedzieć stara wersja.
        _java_path, java_major = LocalLanguageTool.prepare_java_env()
        try:
            import language_tool_python

            version = self.version or LocalLanguageTool.required_lt_version(java_major)
            if version == "brak":
                self.last_error = (
                    f"Java {java_major} jest za stara dla LanguageTool. "
                    "Zainstaluj Javę 17 lub nowszą (adoptium.net).")
                return False
            kwargs = {"language_tool_download_version": version} if version else {}
            self._tool = language_tool_python.LanguageTool(self.language, **kwargs)
            self.last_error = ""
            return True
        except Exception as exc:
            text = str(exc)
            if "Java" in text and ">=" in text and not self.version:
                # Zapas: gdy mimo wszystko wersja nie pasuje, próbujemy LT 5.9.
                try:
                    import language_tool_python

                    self._tool = language_tool_python.LanguageTool(
                        self.language, language_tool_download_version="5.9")
                    self.last_error = ""
                    return True
                except Exception as fallback_exc:
                    text = str(fallback_exc)
            self.last_error = f"LanguageTool offline: {text}"
            self._tool = None
            return False

    def check(self, text: str, disabled_rules: Sequence[str] = ()) -> List[LangIssue]:
        self.last_error = ""
        if not text or not text.strip():
            return []
        if not self.start():
            return []
        masked, spans = mask_codes(text)
        try:
            matches = self._tool.check(masked)
        except Exception as exc:
            self.last_error = f"LanguageTool offline: {exc}"
            return []

        disabled = set(disabled_rules)
        issues: List[LangIssue] = []
        for match in matches:
            rule_id = getattr(match, "rule_id", "") or getattr(match, "ruleId", "")
            if rule_id in disabled:
                continue
            offset = int(getattr(match, "offset", -1))
            length = int(getattr(match, "error_length", 0) or getattr(match, "errorLength", 0))
            if offset >= 0 and _in_spans(offset, length, spans):
                continue
            issue_type = (getattr(match, "rule_issue_type", "") or "").lower()
            if issue_type in ("misspelling", "typographical"):
                severity = SEVERITY_WARNING
            elif issue_type in ("grammar", "inflection", "agreement"):
                severity = SEVERITY_ERROR
            else:
                severity = SEVERITY_INFO
            issues.append(LangIssue(
                category=getattr(match, "category", "") or "Język",
                message=getattr(match, "message", "Uwaga językowa"),
                severity=severity,
                fragment=text[offset:offset + length] if offset >= 0 else "",
                suggestions=list(getattr(match, "replacements", []) or [])[:5],
                offset=offset,
                length=length,
                rule_id=rule_id,
                source="languagetool-offline",
            ))
        return issues

    def close(self) -> None:
        if self._tool is not None:
            try:
                self._tool.close()
            except Exception:
                pass
            self._tool = None


# --------------------------------------------------------- LanguageTool
class LanguageToolClient:
    """Klient LanguageTool (publiczne API albo własny serwer).

    Publiczne API ma limit zapytań, dlatego wyniki są zapamiętywane w pamięci
    podręcznej, a odstęp między zapytaniami jest pilnowany.
    """

    def __init__(self, url: str = LT_PUBLIC_URL, language: str = LT_LANGUAGE,
                 min_interval: float = 0.4, timeout: int = 20) -> None:
        self.url = url or LT_PUBLIC_URL
        self.language = language or LT_LANGUAGE
        self.min_interval = min_interval
        self.timeout = timeout
        self._cache: Dict[str, List[LangIssue]] = {}
        self._last_call = 0.0
        self.last_error = ""

    def check(self, text: str, disabled_rules: Sequence[str] = ()) -> List[LangIssue]:
        """Sprawdza tekst. Zwraca [] i ustawia `last_error`, gdy nie ma połączenia."""
        self.last_error = ""
        if not text or not text.strip():
            return []
        cache_key = f"{self.language}|{text}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        masked, spans = mask_codes(text)
        payload = {
            "text": masked,
            "language": self.language,
            "enabledOnly": "false",
        }
        if disabled_rules:
            payload["disabledRules"] = ",".join(disabled_rules)

        gap = time.monotonic() - self._last_call
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)

        request = urllib.request.Request(
            self.url,
            data=urllib.parse.urlencode(payload).encode("utf-8"),
            headers={"User-Agent": "SuperCAT-Workbench", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            self.last_error = f"LanguageTool: HTTP {exc.code} – {exc.reason}"
            return []
        except Exception as exc:                     # brak sieci, timeout…
            self.last_error = f"LanguageTool niedostępny: {exc}"
            return []
        finally:
            self._last_call = time.monotonic()

        issues = self._parse(data, text, spans)
        self._cache[cache_key] = issues
        if len(self._cache) > 500:
            self._cache.clear()
        return issues

    @staticmethod
    def _parse(data: dict, original: str, spans: Sequence[Tuple[int, int]]) -> List[LangIssue]:
        issues: List[LangIssue] = []
        for match in data.get("matches", []):
            offset = int(match.get("offset", -1))
            length = int(match.get("length", 0))
            if offset >= 0 and _in_spans(offset, length, spans):
                continue        # błąd wskazuje na znacznik – to nie błąd języka
            rule = match.get("rule", {}) or {}
            category = (rule.get("category", {}) or {}).get("name", "Język")
            rule_id = rule.get("id", "")
            issue_type = (rule.get("issueType") or "").lower()
            if issue_type in ("misspelling", "typographical"):
                severity = SEVERITY_WARNING
            elif issue_type in ("grammar", "inflection", "agreement"):
                severity = SEVERITY_ERROR
            else:
                severity = SEVERITY_INFO
            fragment = original[offset:offset + length] if offset >= 0 else ""
            issues.append(LangIssue(
                category=category,
                message=match.get("message", "Uwaga językowa"),
                severity=severity,
                fragment=fragment,
                suggestions=[r.get("value", "") for r in match.get("replacements", [])[:5]],
                offset=offset,
                length=length,
                rule_id=rule_id,
                source="languagetool",
            ))
        return issues


# ------------------------------------------------------------ wejście główne
def default_options() -> dict:
    """Domyślne przełączniki kontroli (odpowiadają Ustawieniom)."""
    return {
        "enabled": True,
        "spelling": True,
        "grammar": True,
        "punctuation": True,
        "skip_uppercase": True,
        "lt_local": False,
        "lt_language": LT_LANGUAGE,
    }


def options_from_settings() -> dict:
    """Czyta przełączniki z Ustawień programu."""
    try:
        from .settings import SettingsManager

        settings = SettingsManager.instance()
        return {
            "enabled": settings.get_bool("lang.check.enabled", True),
            "spelling": settings.get_bool("lang.check.spelling", True),
            "grammar": settings.get_bool("lang.check.grammar", True),
            "punctuation": settings.get_bool("lang.check.punctuation", True),
            "skip_uppercase": settings.get_bool("lang.check.skip.uppercase", True),
            "lt_local": settings.get_bool("lang.check.lt.local", False),
            "lt_language": settings.get("lang.check.lt.language", LT_LANGUAGE) or LT_LANGUAGE,
        }
    except Exception:
        return default_options()


def check_translation(text: str, dictionary=None, use_languagetool: bool = False,
                      client: Optional[LanguageToolClient] = None,
                      disabled_rules: Sequence[str] = (),
                      options: Optional[dict] = None) -> Tuple[List[LangIssue], str]:
    """Sprawdza TŁUMACZENIE. Zwraca (lista uwag, komunikat o błędzie połączenia).

    Kontrola offline działa zawsze; LanguageTool dokłada się do niej, gdy jest
    włączony i dostępny. Uwagi z obu źródeł są scalane, a duplikaty (to samo
    miejsce i ta sama treść) usuwane.
    """
    opts = options if options is not None else options_from_settings()
    if not opts.get("enabled", True):
        return [], ""
    issues = check_offline(text, dictionary, opts)
    error = ""
    if use_languagetool and text and text.strip():
        # Tryb offline (lokalny serwer) ma pierwszeństwo – nie wysyła tekstu
        # w internet i nie ma limitu zapytań.
        if opts.get("lt_local") and client is None:
            lt = LocalLanguageTool.instance(opts.get("lt_language", LT_LANGUAGE))
        else:
            lt = client or LanguageToolClient()
        lt_issues = lt.check(text, disabled_rules)
        error = lt.last_error
        if lt_issues:
            seen: Set[Tuple[int, str]] = {(i.offset, i.category) for i in issues}
            for issue in lt_issues:
                key = (issue.offset, issue.category)
                if key in seen:
                    continue
                seen.add(key)
                issues.append(issue)
            issues.sort(key=lambda i: (i.offset if i.offset >= 0 else 10 ** 6, i.category))
    return issues, error


def fill_suggestions(issues: Sequence[LangIssue], dictionary, limit: int = 5,
                     max_words: int = 12, should_cancel=None, fast: bool = False) -> int:
    """Dolicza propozycje pisowni do gotowych uwag. Zwraca liczbę uzupełnionych.

    Wywoływane po pokazaniu podkreśleń, w osobnym wątku – dzięki temu użytkownik
    od razu widzi, GDZIE jest błąd, a lista propozycji dochodzi chwilę później.
    """
    if dictionary is None or not hasattr(dictionary, "suggest_corrections"):
        return 0
    filled = 0
    for issue in issues:
        if should_cancel is not None and should_cancel():
            break
        if issue.rule_id != "PISOWNIA" or issue.suggestions or not issue.fragment:
            continue
        if filled >= max_words:
            break
        try:
            try:
                issue.suggestions = dictionary.suggest_corrections(
                    issue.fragment, limit, fast=fast)
            except TypeError:               # starsza sygnatura bez `fast`
                issue.suggestions = dictionary.suggest_corrections(issue.fragment, limit)
        except Exception:
            continue
        filled += 1
    return filled


def summarize(issues: Sequence[LangIssue]) -> str:
    """Krótkie podsumowanie do paska stanu."""
    if not issues:
        return "✅ Nie znaleziono uwag językowych"
    errors = sum(1 for i in issues if i.severity == SEVERITY_ERROR)
    warnings = sum(1 for i in issues if i.severity == SEVERITY_WARNING)
    infos = len(issues) - errors - warnings
    parts = []
    if errors:
        parts.append(f"❌ {errors} błędów")
    if warnings:
        parts.append(f"⚠️ {warnings} ostrzeżeń")
    if infos:
        parts.append(f"ℹ️ {infos} uwag")
    return "  •  ".join(parts)


def apply_first_suggestions(text: str, issues: Sequence[LangIssue]) -> Tuple[str, int]:
    """Wstawia pierwszą propozycję dla uwag, które ją mają. Zwraca (tekst, liczba)."""
    usable = [i for i in issues if i.offset >= 0 and i.length > 0 and i.suggestions
              and i.suggestions[0]]
    if not usable:
        return text, 0
    usable.sort(key=lambda i: i.offset, reverse=True)
    out = text
    applied = 0
    last_start = len(text) + 1
    for issue in usable:
        end = issue.offset + issue.length
        if end > last_start:        # nakładające się poprawki – pomijamy
            continue
        out = out[:issue.offset] + issue.suggestions[0] + out[end:]
        last_start = issue.offset
        applied += 1
    return out, applied


# ------------------------------------------- automatyczna korekta po MT
#: Poprawki mechaniczne, bezpieczne dla każdego tekstu (nie zmieniają treści).
_POST_MT_FIXES: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\s+([,.;:!?])"), r"\1"),            # spacja przed znakiem
    (re.compile(r"([,;:])(?=[^\s\d\\])"), r"\1 "),      # brak spacji po przecinku
    (re.compile(r"(?<=\S)[ \t]{2,}(?=\S)"), " "),     # podwójna spacja w środku
    (re.compile(r"\(\s+"), "("),
    (re.compile(r"\s+\)"), ")"),
    (re.compile(r"([„«])\s+"), r"\1"),
    (re.compile(r"\s+([”»])"), r"\1"),
    (re.compile(r"\.{4,}"), "…"),
    (re.compile(r"\s+…"), "…"),
]


def polish_mt_output(text: str, source: str = "") -> Tuple[str, List[str]]:
    """Porządkuje wynik tłumaczenia maszynowego. Zwraca (tekst, lista zmian).

    Silniki MT (Google, MyMemory) często zostawiają spację przed przecinkiem,
    gubią spację po nim albo dublują spacje. To poprawki **mechaniczne** —
    nie zmieniają doboru słów, więc są bezpieczne do wykonania automatycznie.
    Odmiany nie ruszamy: to zadanie dla modelu AI albo dla tłumacza.
    """
    if not text or not text.strip():
        return text, []

    masked, spans = mask_codes(text)
    changes: List[str] = []
    out = text
    for pattern, replacement in _POST_MT_FIXES:
        # pracujemy na wersji zamaskowanej, żeby nie ruszyć znaczników
        masked_now, _ = mask_codes(out)
        if not pattern.search(masked_now):
            continue
        candidate = pattern.sub(replacement, out)
        # bezpiecznik: liczba znaczników musi pozostać ta sama
        if len(CODE_PATTERN.findall(candidate)) == len(CODE_PATTERN.findall(out)):
            if candidate != out:
                out = candidate
                changes.append(pattern.pattern)

    # wielka litera na początku, gdy źródło też ją ma
    if source and source.strip() and out.strip():
        s_first = source.strip()[0]
        t_first = out.strip()[0]
        if s_first.isupper() and t_first.islower() and t_first.isalpha():
            idx = out.index(t_first)
            out = out[:idx] + t_first.upper() + out[idx + 1:]
            changes.append("wielka litera na początku")

    return out, changes
