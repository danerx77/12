"""Glosariusz / termbaza (odpowiednik services/GlossaryService.java).

Plik: <projekt>/glossary/project_glossary.csv
Format wiersza: source|target|opis|część mowy|rodzaj
"""
from __future__ import annotations

import os
import re
import zipfile
from dataclasses import dataclass
from typing import Dict, List, Optional

DEFAULT_ENTRIES = [
    ("hello", "cześć", "Powitanie", "rzeczownik", ""),
    ("world", "świat", "", "rzeczownik", "m"),
    ("translation", "tłumaczenie", "Proces przekładu tekstu", "rzeczownik", "n"),
    ("computer", "komputer", "", "rzeczownik", "m"),
    ("software", "oprogramowanie", "", "rzeczownik", "n"),
    ("network", "sieć", "", "rzeczownik", "ż"),
    ("database", "baza danych", "", "rzeczownik", "ż"),
    ("user", "użytkownik", "", "rzeczownik", "m"),
    ("password", "hasło", "", "rzeczownik", "n"),
    ("save", "zapisz", "", "czasownik", ""),
    ("open", "otwórz", "", "czasownik", ""),
    ("delete", "usuń", "", "czasownik", ""),
]


@dataclass
class GlossaryEntry:
    source: str
    target: str
    description: str = ""
    part_of_speech: str = ""
    gender: str = ""

    def __str__(self) -> str:
        return f"{self.source} → {self.target}"


class Glossary:
    def __init__(self) -> None:
        self.entries: List[GlossaryEntry] = []
        self.file_path: Optional[str] = None

    # ------------------------------------------------------------------
    @property
    def is_initialized(self) -> bool:
        return self.file_path is not None

    def init_for_project(self, glossary_folder: str) -> None:
        os.makedirs(glossary_folder, exist_ok=True)
        path = os.path.join(glossary_folder, "project_glossary.csv")
        self.file_path = path
        if not os.path.exists(path):
            self._create_default()
        self.load()

    def _create_default(self) -> None:
        assert self.file_path
        lines = [
            "# Glosariusz SuperCAT",
            "# Format: source|target|opis|część mowy|rodzaj",
        ]
        for entry in DEFAULT_ENTRIES:
            lines.append("|".join(entry))
        with open(self.file_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")

    def load(self) -> None:
        self.entries = []
        if not self.file_path or not os.path.exists(self.file_path):
            return
        with open(self.file_path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                parts = line.split("|") if "|" in line else line.split("\t")
                if len(parts) < 2:
                    parts = line.split(";")
                if len(parts) < 2:
                    continue
                parts += [""] * (5 - len(parts))
                self.entries.append(
                    GlossaryEntry(parts[0].strip(), parts[1].strip(), parts[2].strip(), parts[3].strip(), parts[4].strip())
                )

    def save(self) -> None:
        if not self.file_path:
            return
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        lines = ["# Glosariusz SuperCAT", "# Format: source|target|opis|część mowy|rodzaj"]
        for e in self.entries:
            lines.append("|".join([e.source, e.target, e.description, e.part_of_speech, e.gender]))
        with open(self.file_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")

    # ------------------------------------------------------------------
    def add(self, source: str, target: str, description: str = "", pos: str = "", gender: str = "") -> None:
        if not source.strip() or not target.strip():
            return
        self.entries.append(GlossaryEntry(source.strip(), target.strip(), description, pos, gender))
        self.save()

    def remove(self, entry: GlossaryEntry) -> None:
        self.entries = [e for e in self.entries if e is not entry]
        self.save()

    def update(self, index: int, entry: GlossaryEntry) -> None:
        if 0 <= index < len(self.entries):
            self.entries[index] = entry
            self.save()

    @property
    def size(self) -> int:
        return len(self.entries)

    # ------------------------------------------------------------------
    def find_terms(self, text: str) -> List[GlossaryEntry]:
        """Znajduje terminy glosariusza występujące w podanym tekście."""
        if not text:
            return []
        lower = text.lower()
        found: List[GlossaryEntry] = []
        for entry in self.entries:
            src = entry.source.lower()
            if not src:
                continue
            if re.search(rf"(?<!\w){re.escape(src)}(?!\w)", lower):
                found.append(entry)
        found.sort(key=lambda e: len(e.source), reverse=True)
        return found

    def replace_in_text(self, text: str, only_if_in: str = "") -> str:
        """Podmienia w tekście terminy źródłowe na tłumaczenia (cały projekt).

        Jak w OmegaT: glosariusz jest jeden na projekt, ale wstawiamy tylko
        frazy, które naprawdę są w tym zdaniu — nigdy nie doklejamy na końcu.
        `only_if_in` (zwykle źródło segmentu) ogranicza do trafień z tego zdania.
        """
        if not text or not self.entries:
            return text
        result = text
        scope = (only_if_in or text)
        terms = sorted(self.entries, key=lambda e: len(e.source or ""), reverse=True)
        for entry in terms:
            src = (entry.source or "").strip()
            tgt = (entry.target or "").strip()
            if len(src) < 2 or not tgt:
                continue
            if src.lower() == tgt.lower():
                continue
            if only_if_in and not re.search(
                    rf"(?<!\w){re.escape(src)}(?!\w)", only_if_in, flags=re.IGNORECASE):
                continue
            if not re.search(rf"(?<!\w){re.escape(src)}(?!\w)", result, flags=re.IGNORECASE):
                continue
            result = re.sub(
                rf"(?<!\w){re.escape(src)}(?!\w)",
                lambda _m, repl=tgt: repl,
                result,
                flags=re.IGNORECASE,
            )
        return result

    def search(self, query: str, in_source: bool = True, in_target: bool = True) -> List[GlossaryEntry]:
        q = (query or "").lower().strip()
        if not q:
            return list(self.entries)
        result = []
        for e in self.entries:
            if (in_source and q in e.source.lower()) or (in_target and q in e.target.lower()):
                result.append(e)
        return result

    # ------------------------------------------------------------------
    def import_file(self, path: str) -> int:
        """Importuje glosariusz z CSV/TSV/TXT (source;target lub source|target)."""
        count = 0
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                for sep in ("|", "\t", ";", ","):
                    if sep in line:
                        parts = [p.strip() for p in line.split(sep)]
                        break
                else:
                    continue
                if len(parts) >= 2 and parts[0] and parts[1]:
                    parts += [""] * (5 - len(parts))
                    self.entries.append(GlossaryEntry(parts[0], parts[1], parts[2], parts[3], parts[4]))
                    count += 1
        self.save()
        return count

    def export_file(self, path: str, separator: str = ";") -> int:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(separator.join(["source", "target", "opis", "część mowy", "rodzaj"]) + "\n")
            for e in self.entries:
                fh.write(separator.join([e.source, e.target, e.description, e.part_of_speech, e.gender]) + "\n")
        return len(self.entries)


#: Słowniki Hunspell do pobrania wprost z programu (repozytorium LibreOffice).
#: Sprawdzone pod kątem dostępności; rozmiary orientacyjne.
#: Do każdego .dic dobieramy też plik .aff – deklaruje kodowanie (np. ISO-8859-2
#: dla polskiego). Bez niego polskie znaki wczytywałyby się jako „�”.
DOWNLOADABLE_DICTIONARIES = [
    # Lista SJP.pl zawiera WSZYSTKIE FORMY ODMIENIONE (4,5 mln), więc działa
    # poprawnie nawet bez silnika Hunspell – „Witamy”, „Dziękujemy”, „Systemu”
    # są w niej wprost. Dlatego jest pierwsza na liście.
    ("polski – pełna odmiana, 4,5 mln form (SJP.pl) ★ zalecany", "sjp_odmiany.txt",
     "https://sjp.pl/sl/odmiany/sjp-odm-20260820.zip", "12 MB (spakowane)"),
    ("polski (pl_PL)", "pl_PL.dic",
     "https://raw.githubusercontent.com/LibreOffice/dictionaries/master/pl_PL/pl_PL.dic", "5,0 MB"),
    ("angielski (en_US)", "en_US.dic",
     "https://raw.githubusercontent.com/LibreOffice/dictionaries/master/en/en_US.dic", "0,5 MB"),
    ("angielski (en_GB)", "en_GB.dic",
     "https://raw.githubusercontent.com/LibreOffice/dictionaries/master/en/en_GB.dic", "0,5 MB"),
    ("niemiecki (de_DE)", "de_DE.dic",
     "https://raw.githubusercontent.com/LibreOffice/dictionaries/master/de/de_DE_frami.dic", "4,2 MB"),
    ("hiszpański (es_ES)", "es_ES.dic",
     "https://raw.githubusercontent.com/LibreOffice/dictionaries/master/es/es_ES.dic", "0,7 MB"),
    ("włoski (it_IT)", "it_IT.dic",
     "https://raw.githubusercontent.com/LibreOffice/dictionaries/master/it_IT/it_IT.dic", "1,2 MB"),
    ("czeski (cs_CZ)", "cs_CZ.dic",
     "https://raw.githubusercontent.com/LibreOffice/dictionaries/master/cs_CZ/cs_CZ.dic", "3,5 MB"),
    ("rosyjski (ru_RU)", "ru_RU.dic",
     "https://raw.githubusercontent.com/LibreOffice/dictionaries/master/ru_RU/ru_RU.dic", "3,3 MB"),
    ("ukraiński (uk_UA)", "uk_UA.dic",
     "https://raw.githubusercontent.com/LibreOffice/dictionaries/master/uk_UA/uk_UA.dic", "8,5 MB"),
]

#: Rozszerzenia plików uznawanych za słownik.
DICTIONARY_EXTENSIONS = (".dic", ".txt")

#: Nazwy kodowań spotykane w plikach .aff → nazwy rozumiane przez Pythona.
_ENCODING_ALIASES = {
    "iso8859-1": "iso8859-1", "iso8859-2": "iso8859-2", "iso8859-13": "iso8859-13",
    "iso8859-15": "iso8859-15", "iso-8859-1": "iso8859-1", "iso-8859-2": "iso8859-2",
    "utf-8": "utf-8", "utf8": "utf-8",
    "microsoft-cp1251": "cp1251", "windows-1250": "cp1250", "windows-1251": "cp1251",
    "windows-1252": "cp1252", "koi8-r": "koi8-r", "koi8-u": "koi8-u",
}


def _normalize_encoding(name: str) -> str:
    """Zamienia nazwę kodowania z pliku .aff na nazwę znaną Pythonowi."""
    key = (name or "").strip().lower()
    if key in _ENCODING_ALIASES:
        return _ENCODING_ALIASES[key]
    try:
        "x".encode(key)
        return key
    except (LookupError, TypeError):
        return "utf-8"


class Dictionary:
    """Prosty słownik wyrazów / sprawdzanie pisowni (Hunspell .dic lub .txt)."""

    def __init__(self) -> None:
        self.words: set[str] = set()
        self.folder: Optional[str] = None
        self.sources: List[str] = []
        #: nazwa pliku -> liczba wczytanych słów (do pokazania na liście)
        self.source_counts: Dict[str, int] = {}
        #: nazwa pliku -> rozpoznane kodowanie (diagnostyka w zakładce Słowniki)
        self.encodings: Dict[str, str] = {}
        #: Silnik Hunspell (spylls) – rozumie odmianę, nie tylko listę wyrazów.
        self._hunspell = None
        self.hunspell_source = ""
        #: Indeks przyspieszający podpowiedzi (budowany przy pierwszym użyciu).
        self._sugg_index = None
        self._sugg_index_size = 0

    @staticmethod
    def detect_encoding(path: str) -> str:
        """Rozpoznaje kodowanie pliku słownika.

        Słowniki Hunspell **nie są w UTF-8** — polski `pl_PL.dic` z LibreOffice
        jest zapisany w ISO-8859-2. Kodowanie deklaruje wiersz ``SET`` w pliku
        `.aff` leżącym obok; gdy go brak, sprawdzamy, czy treść daje się odczytać
        jako UTF-8. Bez tego zamiast „ó” pojawiał się znak zastępczy „�”.
        """
        aff_path = os.path.splitext(path)[0] + ".aff"
        if os.path.isfile(aff_path):
            try:
                with open(aff_path, "rb") as fh:
                    for _ in range(20):
                        line = fh.readline()
                        if not line:
                            break
                        if line.upper().startswith(b"SET "):
                            declared = line[4:].strip().decode("ascii", "ignore").lower()
                            if declared:
                                return _normalize_encoding(declared)
            except Exception:
                pass

        try:
            with open(path, "rb") as fh:
                head = fh.read(2_000_000)
        except Exception:
            return "utf-8"
        if head.startswith(b"\xef\xbb\xbf"):
            return "utf-8-sig"
        try:
            head.decode("utf-8")
            return "utf-8"
        except UnicodeDecodeError:
            pass
        # Wybieramy stronę kodową, która daje najwięcej sensownych liter.
        best, best_score = "iso8859-2", -1
        for candidate in ("iso8859-2", "cp1250", "iso8859-1", "cp1252", "koi8-r", "cp1251"):
            try:
                text = head.decode(candidate)
            except (UnicodeDecodeError, LookupError):
                continue
            score = sum(1 for ch in text if ch.isalpha())
            score -= sum(20 for ch in text if ch in "\ufffd")
            if score > best_score:
                best, best_score = candidate, score
        return best

    def init_for_project(self, dictionary_folder: str) -> None:
        os.makedirs(dictionary_folder, exist_ok=True)
        self.folder = dictionary_folder
        self.words = set()
        self.sources = []
        self.source_counts = {}
        self.encodings = {}
        self._sugg_index = None
        self._sugg_index_size = 0
        for name in sorted(os.listdir(dictionary_folder)):
            if name.lower().endswith(DICTIONARY_EXTENSIONS):
                path = os.path.join(dictionary_folder, name)
                try:
                    before = len(self.words)
                    encoding = self.detect_encoding(path)
                    with open(path, "r", encoding=encoding, errors="replace") as fh:
                        for line in fh:
                            # pierwsza linia .dic to licznik wyrazów
                            word = line.split("/")[0].strip()
                            if word and not word.isdigit() and "\ufffd" not in word:
                                self.words.add(word.lower())
                    self.sources.append(name)
                    self.source_counts[name] = len(self.words) - before
                    self.encodings[name] = encoding
                except Exception as exc:
                    print(f"⚠️ Nie udało się wczytać słownika {name}: {exc}")
        self._load_hunspell()

    # ------------------------------------------------- zarządzanie plikami
    def install_file(self, path: str, folder: Optional[str] = None) -> str:
        """Kopiuje plik słownika do folderu projektu. Zwraca docelową ścieżkę."""
        import shutil

        target_folder = folder or self.folder
        if not target_folder:
            raise ValueError("Nie wskazano folderu słowników (otwórz projekt).")
        if not path.lower().endswith(DICTIONARY_EXTENSIONS):
            raise ValueError("Obsługiwane są pliki .dic (Hunspell) oraz .txt (lista słów).")
        os.makedirs(target_folder, exist_ok=True)
        destination = os.path.join(target_folder, os.path.basename(path))
        if os.path.abspath(path) != os.path.abspath(destination):
            shutil.copy2(path, destination)
        return destination

    def remove_file(self, name: str, folder: Optional[str] = None) -> bool:
        """Usuwa plik słownika z folderu projektu."""
        target_folder = folder or self.folder
        if not target_folder:
            return False
        path = os.path.join(target_folder, name)
        if os.path.isfile(path):
            os.remove(path)
            return True
        return False

    @staticmethod
    def resolve_url(url: str) -> str:
        """Zamienia adres na aktualny, gdy nazwa pliku zawiera datę wydania.

        SJP.pl publikuje listę jako ``sjp-odm-RRRRMMDD.zip`` – nazwa zmienia się
        z każdą aktualizacją, więc zapisany na stałe adres szybko przestałby
        działać. Wyciągamy aktualny odnośnik ze strony z listą.
        """
        import re as _re
        import urllib.request

        if "sjp.pl" not in url or not url.endswith(".zip"):
            return url
        page = url.rsplit("/", 1)[0] + "/"
        try:
            request = urllib.request.Request(page, headers={"User-Agent": "Mozilla/5.0 SuperCAT"})
            with urllib.request.urlopen(request, timeout=30) as response:
                html = response.read().decode("utf-8", errors="replace")
        except Exception:
            return url          # brak sieci – spróbujemy zapisanego adresu
        found = _re.findall(r'href="([^"]*sjp-odm-\d{8}\.zip)"', html)
        if not found:
            return url
        link = found[0]
        if link.startswith("http"):
            return link
        if link.startswith("/"):
            return "https://sjp.pl" + link
        return page + link

    @staticmethod
    def download(url: str, target_path: str,
                 on_progress=None, should_cancel=None) -> int:
        """Pobiera słownik do wskazanego pliku. Zwraca liczbę zapisanych bajtów.

        ``on_progress(pobrane, całość)`` – całość wynosi 0, gdy serwer nie podał
        rozmiaru. ``should_cancel()`` pozwala przerwać pobieranie.
        """
        import urllib.request

        os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
        url = Dictionary.resolve_url(url)
        request = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 SuperCAT-Workbench"})
        temporary = target_path + ".part"
        written = 0
        with urllib.request.urlopen(request, timeout=60) as response:
            total = int(response.headers.get("Content-Length") or 0)
            with open(temporary, "wb") as out:
                while True:
                    if should_cancel is not None and should_cancel():
                        out.close()
                        os.remove(temporary)
                        raise InterruptedError("Pobieranie przerwane")
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    out.write(chunk)
                    written += len(chunk)
                    if on_progress is not None:
                        on_progress(written, total)
        # Archiwum ZIP (np. lista SJP.pl) rozpakowujemy do zwykłego pliku .txt,
        # bo dalsza część programu czyta słowniki jako tekst.
        if zipfile.is_zipfile(temporary):
            written = Dictionary._extract_wordlist(temporary, target_path)
            os.remove(temporary)
            return written

        os.replace(temporary, target_path)
        return written

    @staticmethod
    def _extract_wordlist(archive_path: str, target_path: str) -> int:
        """Wyciąga listę słów z archiwum ZIP i zapisuje jako plik tekstowy.

        Format SJP.pl: jedna linia = formy oddzielone przecinkami
        (``robić, robię, robisz…``). Rozbijamy je na osobne wiersze, żeby
        zwykły odczyt słownika działał bez zmian.
        """
        written = 0
        with zipfile.ZipFile(archive_path) as archive:
            names = [n for n in archive.namelist()
                     if n.lower().endswith((".txt", ".dic")) and "readme" not in n.lower()]
            if not names:
                raise ValueError("Archiwum nie zawiera pliku ze słowami.")
            source = max(names, key=lambda n: archive.getinfo(n).file_size)
            with archive.open(source) as fh, open(target_path, "w", encoding="utf-8") as out:
                for raw in fh:
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    for word in line.split(","):
                        word = word.strip()
                        if word:
                            out.write(word + "\n")
                            written += 1
        return written

    @property
    def is_initialized(self) -> bool:
        return bool(self.words)

    @property
    def size(self) -> int:
        return len(self.words)

    # ---------------------------------------------- pełny silnik Hunspell
    def _load_hunspell(self) -> None:
        """Wczytuje silnik Hunspell (spylls), jeśli jest dostępny.

        Plik `.dic` zawiera wyłącznie formy PODSTAWOWE — formy odmienione
        („dziękujemy”, „systemu”) powstają dopiero z reguł `.aff`. Bez silnika
        połowa poprawnych polskich wyrazów byłaby zgłaszana jako błąd, dlatego
        gdy tylko biblioteka `spylls` jest zainstalowana, korzystamy z niej.
        """
        self._hunspell = None
        self.hunspell_source = ""
        if not self.folder:
            return
        try:
            from spylls.hunspell import Dictionary as _Hunspell
        except ImportError:
            return
        for name in sorted(os.listdir(self.folder)):
            if not name.lower().endswith(".dic"):
                continue
            base = os.path.join(self.folder, name[:-4])
            if not os.path.isfile(base + ".aff"):
                continue        # bez .aff silnik nie zna reguł odmiany
            try:
                self._hunspell = _Hunspell.from_files(base)
                self.hunspell_source = name
                return
            except Exception as exc:
                print(f"⚠️ Hunspell nie wczytał {name}: {exc}")

    @property
    def has_morphology(self) -> bool:
        """True, gdy działa pełna kontrola odmiany (a nie sama lista wyrazów)."""
        return getattr(self, "_hunspell", None) is not None

    #: Formy, których NIE MA w słowniku samych form podstawowych. Jeśli
    #: słownik je zna, znaczy że zawiera odmiany (albo działa Hunspell).
    _INFLECTION_PROBE = ("ofiarę", "zamrozić", "jeźdząc", "chmurę", "dziękujemy")

    def has_inflected_forms(self) -> bool:
        """Czy słownik zna formy odmienione, a nie tylko podstawowe.

        Sam rozmiar bywa mylący (duża lista terminów z gry też ma dużo słów),
        więc sprawdzamy wprost kilka poprawnych polskich form: „ofiarę”,
        „zamrozić”, „jeźdząc”, „chmurę”. Gdy ich nie ma, sprawdzanie pisowni
        zgłasza poprawne słowa jako błędy.
        """
        if self.has_morphology:
            return True
        if not self.words:
            return False
        known = sum(1 for word in self._INFLECTION_PROBE
                    if self.is_correct(word))
        return known >= 3

    def is_correct(self, word: str) -> bool:
        w = word.strip()
        if not w or not any(ch.isalpha() for ch in w):
            return True
        engine = getattr(self, "_hunspell", None)
        if engine is not None:
            try:
                if engine.lookup(w) or engine.lookup(w.lower()):
                    return True
                # Nazwy własne pisane wersalikami (MYSTERY, GIFT) sprawdzamy
                # też w postaci z wielkiej litery – Hunspell tak je zapisuje.
                if w.isupper() and engine.lookup(w.capitalize()):
                    return True
                return False
            except Exception:
                pass
        if not self.words:
            return True
        return w.lower() in self.words

    def check_text(self, text: str, skip_uppercase: bool = True) -> List[str]:
        """Zwraca listę słów spoza słownika.

        ``skip_uppercase`` pomija wyrazy pisane WERSALIKAMI — w plikach gier to
        nazwy własne (MYSTERY, GIFT, STAMP CARD), których nie ma w żadnym
        słowniku, a zgłaszanie ich zalewałoby panel.
        """
        if not text or (not self.words and not self.has_morphology):
            return []
        unknown = []
        seen = set()
        for word in re.findall(r"[^\W\d_]+", text, flags=re.UNICODE):
            if len(word) <= 2 or word in seen:
                continue
            if skip_uppercase and word.isupper():
                continue
            seen.add(word)
            if not self.is_correct(word):
                unknown.append(word)
        return unknown

    def suggest(self, prefix: str, max_results: int = 20) -> List[str]:
        p = (prefix or "").lower()
        if not p:
            return []
        out = [w for w in self.words if w.startswith(p)]
        out.sort()
        return out[:max_results]

    def suggest_corrections(self, word: str, limit: int = 5, fast: bool = False) -> List[str]:
        """Propozycje poprawnej pisowni – wyrazy o zbliżonym zapisie.

        Kandydatów zawężamy po długości i pierwszej literze, dopiero potem
        liczymy odległość edycyjną. Bez tego przy słowniku 350 tys. wyrazów
        każde sprawdzenie trwałoby sekundy.
        """
        w = (word or "").strip().lower()
        if not w:
            return []
        # Hunspell daje najlepsze propozycje, ale liczy je ok. 3 s na wyraz.
        # `fast=True` pomija go i korzysta z szybkiego dopasowania po formach
        # podstawowych (~0,1 s) – pokazujemy coś od razu, a dokładne wyniki
        # dochodzą chwilę później.
        engine = None if fast else getattr(self, "_hunspell", None)
        if engine is not None:
            try:
                out = []
                for suggestion in engine.suggest(word.strip()):
                    out.append(suggestion)
                    if len(out) >= limit:
                        break
                if out:
                    return out
            except Exception:
                pass
        if not self.words:
            return []
        try:
            from rapidfuzz import process as _process, fuzz as _fuzz
            has_rapidfuzz = True
        except ImportError:
            has_rapidfuzz = False

        span = 2 if len(w) > 4 else 1
        # Przy 4,5 mln form przejście całego zbioru trwa ~1,5 s. Indeks
        # (pierwsza litera, długość) zawęża listę do kilkuset kandydatów.
        index = self._suggest_index()
        candidates: List[str] = []
        if index is not None:
            first_letters = {w[:1]}
            if len(w) > 1:
                first_letters.add(w[1:2])      # literówka w pierwszej literze
            for letter in first_letters:
                for length in range(len(w) - span, len(w) + span + 1):
                    candidates.extend(index.get((letter, length), ()))
        else:
            candidates = [
                x for x in self.words
                if abs(len(x) - len(w)) <= span and (x[:1] == w[:1] or x[1:2] == w[1:2])
            ]
        if not candidates:
            return []
        if has_rapidfuzz:
            found = _process.extract(w, candidates, scorer=_fuzz.ratio,
                                     limit=limit, score_cutoff=70)
            return [name for name, _score, _idx in found]
        import difflib

        return difflib.get_close_matches(w, candidates, n=limit, cutoff=0.7)

    def _suggest_index(self) -> Optional[Dict[tuple, List[str]]]:
        """Buduje (raz) indeks (pierwsza litera, długość) → wyrazy."""
        if getattr(self, "_sugg_index", None) is not None and \
                self._sugg_index_size == len(self.words):
            return self._sugg_index
        if not self.words:
            return None
        index: Dict[tuple, List[str]] = {}
        for word in self.words:
            index.setdefault((word[:1], len(word)), []).append(word)
        self._sugg_index = index
        self._sugg_index_size = len(self.words)
        return index

    def lookup(self, word: str) -> List[str]:
        """Prosta 'definicja' – lista podobnych form ze słownika."""
        w = (word or "").lower().strip()
        if not w:
            return []
        result = [x for x in self.words if x.startswith(w[: max(3, len(w) - 2)])]
        result.sort(key=lambda x: (abs(len(x) - len(w)), x))
        return result[:30]
