"""Tłumaczenie maszynowe (odpowiednik services/MachineTranslationService.java).

Silniki: LOCAL (słownikowy), DeepL (Pro/Free), OpenAI, LibreTranslate,
Google (darmowy endpoint), IBM Watson, AI Offline (własny endpoint HTTP).
Klucze API trzymane są w ~/.supercat/api_keys.json
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple

from .settings import APP_DIR, SettingsManager
from .ai_clean import build_translation_prompt, clean_ai_translation
from .usage import UsageTracker

API_KEYS_FILE = os.path.join(APP_DIR, "api_keys.json")

ENGINES = [
    ("local", "Lokalny (słownikowy, offline)"),
    ("google_free", "Google Translate (bez klucza API)"),
    ("microsoft_free", "Microsoft Translator / Bing (bez klucza API)"),
    ("deepl_web", "DeepL przez stronę (bez klucza, limit zapytań)"),
    ("mymemory", "MyMemory (bez klucza API)"),
    ("libretranslate", "LibreTranslate (własny serwer)"),
    ("azure", "Azure Translator (klucz, 2 mln zn./mies.)"),
    ("deepl", "DeepL API (Pro)"),
    ("deepl_free", "DeepL API Free"),
    ("openai", "OpenAI / kompatybilne API"),
    ("gemini", "Google Gemini (AI Studio – darmowy klucz)"),
    ("puter", "Puter AI – Gemma, GPT, Claude (darmowy token)"),
    ("ibm_watson", "IBM Watson Language Translator"),
    ("ai_offline", "AI Offline (własny endpoint HTTP)"),
]

#: Google Gemini – API z Google AI Studio (https://aistudio.google.com/apikey).
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_DEFAULT_MODEL = "gemini-flash-latest"

#: Kandydaci na model, od najnowszych. Google blokuje starsze modele (2.5)
#: dla nowo utworzonych projektów ("no longer available to new users"),
#: dlatego program potrafi sam wykryć, co jest dostępne dla danego klucza.
GEMINI_MODELS = [
    "gemini-flash-latest",       # alias – zawsze wskazuje aktualny model Flash
    "gemini-3-flash-preview",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",          # starsze – działają tylko na kontach z historią
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
]

#: Puter AI Gateway – endpoint zgodny z OpenAI (dostęp do 500+ modeli).
PUTER_DEFAULT_URL = "https://api.puter.com/puterai/openai/v1/chat/completions"
PUTER_DEFAULT_MODEL = "google/gemma-3-27b-it"

#: Modele Puter przydatne przy tłumaczeniu (można wpisać dowolny inny).
PUTER_MODELS = [
    "google/gemma-3-27b-it",
    "google/gemini-2.0-flash",
    "gpt-4o-mini",
    "claude-sonnet-4",
    "deepseek-chat",
]

#: Silniki oparte na modelach językowych – rozumieją kontekst całego segmentu,
#: więc NIE dzielimy im tekstu na linie (traciłyby sens zdania).
AI_ENGINES = {"gemini", "openai", "puter", "ai_offline"}

#: Silniki, którym wysyłamy segment W CAŁOŚCI (jedno zapytanie na segment).
#: DeepL przez stronę ma ostry limit na adres IP, a dzielenie po \n i \p
#: zamieniało jeden segment w 2–4 osobne zapytania – limit wyczerpywał się
#: natychmiast, zanim użytkownik zdążył cokolwiek przetłumaczyć.
WHOLE_SEGMENT_ENGINES = AI_ENGINES | {"deepl_web"}

#: Silniki działające bez klucza API – używane przez zbiorcze tłumaczenie / QuickTrans.
FREE_ENGINES = ["google_free", "microsoft_free", "deepl_web", "mymemory",
                "libretranslate", "local"]

#: Krótkie kody dostawców (jak kolorowe „pigułki” w Supervertaler QuickTrans).
ENGINE_CODES = {
    "local": "LOC", "google_free": "GT", "microsoft_free": "MS", "mymemory": "MM",
    "libretranslate": "LT", "azure": "AZ", "deepl_web": "DLW",
    "deepl": "DL", "deepl_free": "DL", "openai": "GPT", "ibm_watson": "IBM",
    "ai_offline": "AI", "gemini": "GEM", "puter": "PUT",
}

#: Pełne nazwy języków -> kody ISO (MyMemory i Google wymagają kodów).
LANG_NAME_TO_CODE = {
    "polski": "pl", "polish": "pl", "angielski": "en", "english": "en",
    "niemiecki": "de", "german": "de", "francuski": "fr", "french": "fr",
    "hiszpański": "es", "spanish": "es", "włoski": "it", "italian": "it",
    "niderlandzki": "nl", "dutch": "nl", "czeski": "cs", "czech": "cs",
    "rosyjski": "ru", "russian": "ru", "ukraiński": "uk", "ukrainian": "uk",
    "portugalski": "pt", "portuguese": "pt", "szwedzki": "sv", "swedish": "sv",
    "chiński": "zh", "chinese": "zh", "japoński": "ja", "japanese": "ja",
    "koreański": "ko", "korean": "ko",
}


#: Wzorce chronione przed silnikiem MT: znaczniki sterujące, zmienne, tagi.
_PROTECT_PATTERNS = [
    re.compile(r"\\[a-zA-Z]"),      # \n \p \l \c ...
    re.compile(r"\{[^}]{0,60}\}"),  # {PLAYER}, {STR_VAR_1}
    re.compile(r"\[[^\]]{0,60}\]"), # [BUTTON]
    re.compile(r"<[^>]{0,60}>"),    # <b>, </i>
]

#: Wzorzec odnajdujący token nawet po tym, jak MT doda spacje lub zmieni wielkość liter.
_TOKEN_FIND_RE = re.compile(r"@\s*#\s*(\d{1,3})\s*#\s*@", re.IGNORECASE)


def protect_codes(text: str) -> Tuple[str, List[str]]:
    """Zastępuje znaczniki neutralnymi tokenami przed wysłaniem do silnika MT.

    Silniki (zwłaszcza MyMemory i Google) traktują ``\\n`` jak zwykły tekst
    i potrafią zwrócić ``\\ n`` – z wstawioną spacją – albo przenieść znacznik
    w inne miejsce. Token ``@#0#@`` przechodzi przez tłumaczenie nietknięty,
    a po powrocie jest zamieniany z powrotem na oryginalny znacznik.
    """
    if not text:
        return "", []
    placeholders: List[str] = []

    def replace(match: "re.Match[str]") -> str:
        placeholders.append(match.group(0))
        return f"@#{len(placeholders) - 1}#@"

    result = text
    for pattern in _PROTECT_PATTERNS:
        result = pattern.sub(replace, result)
    return result, placeholders


#: Ostatnie odtworzenie znaczników – ile z nich model zgubił.
LAST_RESTORE_STATS = {"expected": 0, "missing": 0}


def restore_codes(text: str, placeholders: List[str]) -> str:
    """Przywraca oryginalne znaczniki w miejsce tokenów.

    Odporne na typowe uszkodzenia wprowadzane przez MT: dodatkowe spacje
    wewnątrz tokenu, zmieniona wielkość liter, spacja doklejona przed
    znacznikiem. Tokeny, których silnik nie zwrócił, są dopisywane na końcu,
    żeby żaden znacznik nie zniknął.
    """
    if not placeholders:
        return text
    used: set[int] = set()

    def put_back(match: "re.Match[str]") -> str:
        index = int(match.group(1))
        if 0 <= index < len(placeholders):
            used.add(index)
            return placeholders[index]
        return match.group(0)

    result = _TOKEN_FIND_RE.sub(put_back, text)

    # awaryjnie: token mógł stracić znaki @ lub #
    for index, original in enumerate(placeholders):
        if index in used:
            continue
        loose = re.compile(rf"@?\s*#\s*{index}\s*#\s*@?")
        if loose.search(result):
            result = loose.sub(lambda _m, o=original: o, result, count=1)
            used.add(index)

    # Silniki MT dopisują spacje wokół znaczników sterujących ("\n VERMILION",
    # "porcie \nCITY"). W plikach gier \n i \p to przełamy linii – przylegają
    # bezpośrednio do tekstu, więc doklejone spacje usuwamy.
    result = re.sub(r"[ \t]*(\\[a-zA-Z])[ \t]*", r"\1", result)

    missing = [placeholders[i] for i in range(len(placeholders)) if i not in used]
    LAST_RESTORE_STATS["expected"] = len(placeholders)
    LAST_RESTORE_STATS["missing"] = len(missing)
    if missing:
        # Model zgubił znaczniki – dopisujemy je na końcu, żeby nie zniknęły
        # z pliku. Informacja trafia do dziennika AI, bo wymaga sprawdzenia.
        result = result.rstrip() + "".join(missing)
    return result


#: Rozbicie tekstu na kawałki z zachowaniem separatorów (\n, \p ...).
_SEG_SPLIT_RE = re.compile(r"(\\[a-zA-Z])")


def split_keep_separators(text: str) -> List[str]:
    """Dzieli tekst na fragmenty, zachowując znaczniki jako osobne elementy."""
    return [part for part in _SEG_SPLIT_RE.split(text) if part != ""]


def split_into_sentences_with_codes(text: str) -> List[Tuple[str, List[str]]]:
    """Dzieli tekst na ZDANIA, nie na linie.

    Znacznik `\n` bardzo często przełamuje zdanie w środku
    (``the STAMP CARD\nSystem.`` to jedna nazwa). Tłumaczenie takich kawałków
    osobno dawało bezsens („System.” jako oddzielne zdanie). Dlatego grupujemy
    fragmenty aż do znaku kończącego zdanie, a znaczniki z wnętrza zapamiętujemy,
    by wstawić je z powrotem po przetłumaczeniu.

    Zwraca listę par ``(tekst_zdania, znaczniki_wewnętrzne)``; elementy będące
    samym znacznikiem mają pusty tekst.
    """
    parts = split_keep_separators(text)
    result: List[Tuple[str, List[str]]] = []
    buffer: List[str] = []
    inner: List[str] = []

    def flush() -> None:
        if buffer:
            result.append(("".join(buffer), list(inner)))
            buffer.clear()
            inner.clear()

    for part in parts:
        if _SEG_SPLIT_RE.fullmatch(part):
            # \p (nowa strona) zawsze kończy wypowiedź
            if part.lower().endswith("p"):
                flush()
                result.append(("", [part]))
            elif buffer and buffer[-1].rstrip().endswith((".", "!", "?", ":", "…")):
                flush()                      # zdanie się skończyło – znacznik osobno
                result.append(("", [part]))
            elif buffer:
                inner.append(part)           # przełamanie WEWNĄTRZ zdania
                buffer.append(" ")
            else:
                result.append(("", [part]))
        else:
            buffer.append(part)
    flush()
    return result


def restore_inner_codes(translated: str, codes: List[str]) -> str:
    """Wstawia znaczniki przełamujące z powrotem do przetłumaczonego zdania.

    Rozmieszcza je równomiernie na granicach wyrazów, tak aby wiersze miały
    zbliżoną długość — to odpowiada układowi oryginału.
    """
    if not codes:
        return translated
    words = translated.split(" ")
    if len(words) <= len(codes):
        return translated + "".join(codes)
    chunk = len(words) / (len(codes) + 1)
    out: List[str] = []
    next_break = 0
    for index, word in enumerate(words):
        if next_break < len(codes) and index >= round(chunk * (next_break + 1)) and index > 0:
            out.append(codes[next_break])
            next_break += 1
        elif index > 0:
            out.append(" ")
        out.append(word)
    for leftover in codes[next_break:]:
        out.append(leftover)
    return "".join(out)


def to_lang_code(value: str) -> str:
    """Zamienia nazwę języka lub kod z regionem na dwuliterowy kod ISO."""
    if not value:
        return "en"
    v = value.strip().lower()
    if v in LANG_NAME_TO_CODE:
        return LANG_NAME_TO_CODE[v]
    return v.split("-")[0].split("_")[0][:2]

LOCAL_DICT: Dict[str, str] = {
    "hello": "witaj", "world": "świat", "translation": "tłumaczenie", "memory": "pamięć",
    "system": "system", "helps": "pomaga", "work": "pracować", "efficiently": "efektywnie",
    "good morning": "dzień dobry", "good night": "dobranoc", "thank you": "dziękuję",
    "please": "proszę", "file": "plik", "open": "otwórz", "save": "zapisz", "close": "zamknij",
    "settings": "ustawienia", "project": "projekt", "user": "użytkownik", "document": "dokument",
    "language": "język", "source": "źródło", "target": "cel", "text": "tekst", "search": "szukaj",
}


class MachineTranslation:
    def __init__(self) -> None:
        self.keys: Dict[str, str] = {
            "deepl": "", "openai": "", "openai_model": "gpt-4o-mini",
            "openai_url": "https://api.openai.com/v1/chat/completions",
            "libretranslate_url": "http://localhost:5000", "libretranslate_key": "",
            "ibm_watson_key": "", "ibm_watson_url": "",
            "ai_offline_url": "http://localhost:8000/translate",
            "mymemory": "", "mymemory_email": "",
            "gemini": "", "gemini_model": GEMINI_DEFAULT_MODEL,
            "puter_token": "",
            "puter_url": "https://api.puter.com/puterai/openai/v1/chat/completions",
            "puter_model": "google/gemma-3-27b-it",
            "azure_key": "", "azure_region": "",
            "azure_endpoint": "https://api.cognitive.microsofttranslator.com",
        }
        #: Sesja darmowego tłumacza Bing (token ważny ok. godziny).
        self._bing_cache: Optional[dict] = None
        #: Widoki powiadamiane o zmianie silnika (Edytor, Ustawienia, panel AI).
        self._engine_listeners: List = []
        self.engine = SettingsManager.instance().get_str("mt.engine", "local")
        #: Tokeny zgłoszone przez ostatnie wywołanie (jeśli silnik je zwraca)
        self._last_tokens = 0
        #: Dodatkowe wytyczne dla modeli AI (Ustawienia → MT → Wytyczne dla AI)
        self.ai_instructions = SettingsManager.instance().get_str("mt.ai.instructions", "")
        self.load_keys()

    # ------------------------------------------------------------------
    def load_keys(self) -> None:
        try:
            if os.path.exists(API_KEYS_FILE):
                with open(API_KEYS_FILE, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    self.keys.update({k: str(v) for k, v in data.items()})
        except Exception as exc:
            print(f"⚠️ Brak/nieprawidłowe klucze API ({exc}) – tryb lokalny.")

    def save_keys(self) -> None:
        os.makedirs(APP_DIR, exist_ok=True)
        with open(API_KEYS_FILE, "w", encoding="utf-8") as fh:
            json.dump(self.keys, fh, ensure_ascii=False, indent=2)

    def add_engine_listener(self, callback) -> None:
        """Rejestruje funkcję wywoływaną po każdej zmianie silnika.

        Silnik da się przestawić z trzech miejsc (Ustawienia, lista w Edytorze,
        panel AI) — bez powiadomienia pozostałe pokazywały nieaktualną nazwę.
        """
        self._engine_listeners.append(callback)

    def set_engine(self, engine: str) -> None:
        self.engine = engine
        SettingsManager.instance().set("mt.engine", engine)
        for callback in list(self._engine_listeners):
            try:
                callback(engine)
            except Exception:
                pass          # zepsuty widok nie może zablokować tłumaczenia

    @property
    def engine_label(self) -> str:
        return dict(ENGINES).get(self.engine, self.engine)

    # ------------------------------------------------------------------
    def translate(self, text: str, source_lang: str = "en", target_lang: str = "pl",
                  engine: Optional[str] = None) -> str:
        """Tłumaczy tekst; ``engine`` pozwala wskazać silnik na jedno wywołanie.

        Silnik jest przekazywany **parametrem**, a nie przez podmianę
        ``self.engine``. Wcześniejsza wersja podmieniała pole obiektu i wracała
        do poprzedniej wartości — przy równoległym QuickTransie wątki nadpisywały
        sobie ustawienie nawzajem (wyniki trafiały do złych silników, a lista
        silnika w interfejsie potrafiła zostać na przypadkowej pozycji).
        """
        engine = engine or self.engine
        if not text or not text.strip():
            return ""

        # Tryb „linia po linii”: proste silniki MT (Google, MyMemory) przestawiają
        # znaczniki końca wiersza, więc każdą linię tłumaczymy osobno.
        #
        # Modele AI (Gemini, OpenAI, Puter) są z tego WYŁĄCZONE: dzielenie odbiera
        # im kontekst — fragment „System.” bez reszty zdania dawał przypadkowe
        # tłumaczenia i warianty typu „X or Y”. AI dostaje cały segment naraz,
        # a znaczniki i tak chroni mechanizm protect_codes/restore_codes.
        if (SettingsManager.instance().get_bool("mt.translate.by.line", True)
                and engine not in WHOLE_SEGMENT_ENGINES
                and _SEG_SPLIT_RE.search(text)):
            out: List[str] = []
            for chunk, inner_codes in split_into_sentences_with_codes(text):
                if not chunk:
                    out.append("".join(inner_codes))   # sam znacznik – bez zmian
                elif not chunk.strip():
                    out.append(chunk)
                else:
                    translated = self._translate_one(chunk, source_lang, target_lang, engine)
                    out.append(restore_inner_codes(translated, inner_codes))
            return "".join(out)

        return self._translate_one(text, source_lang, target_lang, engine)

    def _translate_one(self, text: str, source_lang: str, target_lang: str,
                       engine: Optional[str] = None) -> str:
        """Tłumaczy pojedynczy fragment (bez dzielenia po znacznikach)."""
        self._last_polish_changes: List[str] = []
        self._last_fallback = ""
        if not text or not text.strip():
            return text
        # Pozostałe znaczniki ({ZMIENNA}, <tag>) chowamy przed silnikiem MT.
        protected, placeholders = protect_codes(text)
        self._last_tokens = 0
        engine_used = engine or self.engine
        try:
            if engine_used == "deepl":
                result = self._deepl(protected, source_lang, target_lang, free=False)
            elif engine_used == "deepl_free":
                result = self._deepl(protected, source_lang, target_lang, free=True)
            elif engine_used == "openai":
                result = self._openai(protected, source_lang, target_lang)
            elif engine_used == "gemini":
                result = self._gemini(protected, source_lang, target_lang)
            elif engine_used == "puter":
                result = self._puter(protected, source_lang, target_lang)
            elif engine_used == "libretranslate":
                result = self._libretranslate(protected, source_lang, target_lang)
            elif engine_used == "mymemory":
                result = self._mymemory(protected, source_lang, target_lang)
            elif engine_used == "google_free":
                result = self._google_free(protected, source_lang, target_lang)
            elif engine_used == "microsoft_free":
                result = self._microsoft_free(protected, source_lang, target_lang)
            elif engine_used == "deepl_web":
                result = self._deepl_web(protected, source_lang, target_lang)
            elif engine_used == "azure":
                result = self._azure(protected, source_lang, target_lang)
            elif engine_used == "ibm_watson":
                result = self._ibm_watson(protected, source_lang, target_lang)
            elif engine_used == "ai_offline":
                result = self._ai_offline(protected, source_lang, target_lang)
            else:
                result = self._local(protected)
        except Exception as exc:
            # policz też nieudane wywołania – widać, że limit został wyczerpany
            UsageTracker.instance().record(engine_used, chars=len(text), error=True)

            # DeepL przez stronę bywa zablokowany zanim użytkownik cokolwiek
            # przetłumaczy. Zamiast oddawać sam komunikat o błędzie, sięgamy po
            # Microsoft (bez klucza, ta sama jakość klasy neuronowej) i mówimy
            # wprost, że wynik pochodzi z zamiennika.
            if (engine_used == "deepl_web"
                    and SettingsManager.instance().get_bool(
                        "mt.deepl.web.fallback", True)):
                try:
                    spare = self._microsoft_free(protected, source_lang, target_lang)
                except Exception:
                    return f"[Błąd MT: {exc}]"
                self._last_fallback = (
                    "DeepL przez stronę jest zablokowany (limit zapytań) — "
                    "użyto silnika Microsoft (bez klucza).")
                UsageTracker.instance().record("microsoft_free", chars=len(text))
                return restore_codes(spare, placeholders)
            return f"[Błąd MT: {exc}]"
        # Zapis zużycia: liczba znaków oraz tokeny, jeśli silnik je zgłasza.
        UsageTracker.instance().record(
            engine_used, chars=len(text), tokens=getattr(self, "_last_tokens", 0) or 0
        )
        output = restore_codes(result, placeholders)

        # Porządki po silniku MT: spacja przed przecinkiem, brak spacji po nim,
        # podwójne spacje. Poprawki są czysto mechaniczne – nie zmieniają słów,
        # więc nie mogą zepsuć tłumaczenia. Odmianą zajmuje się model AI.
        if SettingsManager.instance().get_bool("mt.polish.output", True):
            from .langcheck import polish_mt_output

            output, changes = polish_mt_output(output, text)
            if changes:
                self._last_polish_changes = changes
        return output

    #: Ile tekstów naraz przyjmuje wewnętrzne API strony DeepL.
    DEEPL_WEB_BATCH = 10

    def translate_batch(self, texts: List[str], source_lang: str, target_lang: str,
                        engine: Optional[str] = None) -> List[str]:
        """Tłumaczy listę tekstów; DeepL przez stronę – paczkami.

        Zwykłe silniki tłumaczą segment po segmencie. DeepL WWW ma ostry limit
        zapytań (pomiar: 6 z 8 pojedynczych zapytań pod rząd, potem 429), ale
        przyjmuje **kilkanaście tekstów w jednym zapytaniu** — 10 segmentów
        zajęło 0,8 s. Dzięki temu cały plik da się przetłumaczyć jednym silnikiem
        bez wpadania w limit.
        """
        engine = engine or self.engine
        if engine != "deepl_web" or len(texts) < 2:
            return [self.translate(t, source_lang, target_lang, engine) for t in texts]

        results: List[str] = []
        for start in range(0, len(texts), self.DEEPL_WEB_BATCH):
            chunk = texts[start:start + self.DEEPL_WEB_BATCH]
            protected = [protect_codes(t) for t in chunk]
            try:
                translated = self._deepl_web_request(
                    [p for p, _c in protected], source_lang, target_lang)
            except Exception as exc:
                UsageTracker.instance().record(
                    "deepl_web", chars=sum(len(t) for t in chunk), error=True)
                if SettingsManager.instance().get_bool("mt.deepl.web.fallback", True):
                    # Zapas: Microsoft nie ma takich limitów, więc tłumaczenie
                    # całego pliku nie zatrzymuje się na pierwszej paczce.
                    self._last_fallback = (
                        "DeepL przez stronę zablokowany — dalej tłumaczy Microsoft.")
                    results.extend(
                        self.translate(t, source_lang, target_lang, "microsoft_free")
                        for t in chunk)
                else:
                    results.extend(f"[Błąd MT: {exc}]" for _ in chunk)
                continue
            UsageTracker.instance().record(
                "deepl_web", chars=sum(len(t) for t in chunk))
            for (_prot, codes), out, original in zip(protected, translated, chunk):
                restored = restore_codes(out, codes)
                if SettingsManager.instance().get_bool("mt.polish.output", True):
                    from .langcheck import polish_mt_output

                    restored, _changes = polish_mt_output(restored, original)
                results.append(restored)
        return results

    # ------------------------------------------------------------- silniki
    #: Zewnętrzne źródła słownictwa dla silnika lokalnego (ustawiane przez program).
    tm_provider = None          # obiekt TranslationMemory
    glossary_provider = None    # obiekt Glossary

    def local_vocabulary(self) -> Dict[str, str]:
        """Buduje słownik silnika lokalnego: glosariusz + pamięć TM + wbudowany.

        Wbudowana lista ma 25 haseł i służyła wyłącznie do pokazania działania —
        stąd „WIRELESS COMMUNICATION” wracało nieprzetłumaczone. Teraz silnik
        korzysta przede wszystkim z terminów projektu, więc faktycznie tłumaczy
        to, co już raz przetłumaczyłeś.
        """
        vocabulary: Dict[str, str] = dict(LOCAL_DICT)

        glossary = self.glossary_provider
        if glossary is not None:
            for entry in getattr(glossary, "entries", []) or []:
                source = (getattr(entry, "source", "") or "").strip().lower()
                target = (getattr(entry, "target", "") or "").strip()
                if source and target:
                    vocabulary[source] = target

        memory = self.tm_provider
        if memory is not None and getattr(memory, "is_initialized", False):
            try:
                # Krótkie wpisy TM to w praktyce terminy – dłuższe zdania
                # podstawiane fragmentami dawałyby bełkot.
                for source, target, *_rest in memory.all_entries(limit=4000):
                    key = (source or "").strip().lower()
                    value = (target or "").strip()
                    if key and value and len(key) <= 40 and "\n" not in key:
                        vocabulary.setdefault(key, value)
            except Exception:
                pass
        return vocabulary

    def _local(self, text: str) -> str:
        vocabulary = self.local_vocabulary()
        result = text
        # Najpierw najdłuższe hasła – inaczej „stamp” zjadłoby „stamp card”.
        for src, tgt in sorted(vocabulary.items(), key=lambda kv: len(kv[0]), reverse=True):
            result = _replace_ci(result, src, tgt)

        if result.strip().lower() == text.strip().lower():
            # Nic nie pasowało – mówimy o tym wprost, zamiast oddawać oryginał
            # udający tłumaczenie.
            return (f"[MT lokalne: brak w słowniku ({len(vocabulary)} haseł) – "
                    f"dodaj termin do glosariusza] {text}")
        return f"[MT lokalne] {result}"

    def _http_post(self, url: str, data: bytes, headers: Dict[str, str], timeout: int = 30) -> dict:
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _deepl(self, text: str, sl: str, tl: str, free: bool) -> str:
        key = self.keys.get("deepl", "").strip()
        if not key:
            # DeepL nie ma trybu anonimowego: publiczne obejścia zwracają
            # 403/451 (blokada prawna), więc jedyną drogą jest darmowy klucz.
            raise RuntimeError(
                "DeepL wymaga klucza — nie udostępnia tłumaczenia bez rejestracji. "
                "Plan DeepL API Free daje 500 000 znaków miesięcznie za darmo: "
                "załóż konto na deepl.com/pro-api i wklej klucz w "
                "Ustawieniach → Tłumaczenie maszynowe. "
                "Bez klucza użyj Google, MyMemory albo LibreTranslate."
            )
        host = "api-free.deepl.com" if free or key.endswith(":fx") else "api.deepl.com"
        params = {"text": text, "target_lang": to_lang_code(tl).upper()}
        if sl and sl.lower() != "auto":
            params["source_lang"] = to_lang_code(sl).upper()
        formality = SettingsManager.instance().get_str("mt.deepl.formality", "default")
        if formality and formality != "default":
            params["formality"] = formality
        data = urllib.parse.urlencode(params).encode()
        headers = {
            "Authorization": f"DeepL-Auth-Key {key}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        result = self._http_post(f"https://{host}/v2/translate", data, headers)
        return result["translations"][0]["text"]

    def _openai(self, text: str, sl: str, tl: str) -> str:
        key = self.keys.get("openai", "").strip()
        if not key:
            raise RuntimeError("Brak klucza OpenAI (Ustawienia → MT).")
        url = self.keys.get("openai_url") or "https://api.openai.com/v1/chat/completions"
        model = self.keys.get("openai_model") or "gpt-4o-mini"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": build_translation_prompt(sl, tl, self.ai_instructions)},
                {"role": "user", "content": text},
            ],
            "temperature": 0.2,
        }
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        result = self._http_post(url, json.dumps(payload).encode("utf-8"), headers, timeout=60)
        usage = result.get("usage") or {}
        self._last_tokens = int(usage.get("total_tokens") or 0)
        return clean_ai_translation(result["choices"][0]["message"]["content"], text)

    def _libretranslate(self, text: str, sl: str, tl: str) -> str:
        base = (self.keys.get("libretranslate_url") or "http://localhost:5000").rstrip("/")
        payload = {"q": text, "source": to_lang_code(sl) or "auto", "target": to_lang_code(tl), "format": "text"}
        api_key = self.keys.get("libretranslate_key", "").strip()
        if api_key:
            payload["api_key"] = api_key
        headers = {"Content-Type": "application/json"}
        try:
            result = self._http_post(f"{base}/translate", json.dumps(payload).encode(), headers)
        except urllib.error.URLError as exc:
            # Domyślnie wskazuje na localhost:5000 – bez uruchomionego serwera
            # użytkownik dostawał surowe „WinError 10061”, z którego nic nie wynika.
            local = "localhost" in base or "127.0.0.1" in base
            hint = ("Uruchom własny serwer LibreTranslate albo wpisz adres publicznego "
                    "serwera w Ustawieniach → Tłumaczenie maszynowe."
                    if local else "Sprawdź adres serwera w Ustawieniach → Tłumaczenie maszynowe.")
            raise RuntimeError(f"LibreTranslate niedostępny pod adresem {base}. {hint}") from exc
        return result.get("translatedText", "")

    def _google_free(self, text: str, sl: str, tl: str) -> str:
        """Darmowe tłumaczenie Google – z zapasowym punktem dostępowym.

        Adres `gtx` ma ostry limit zapytań na adres IP i po kilkunastu wywołaniach
        pod rząd zwraca `429 Too Many Requests` na dłuższą chwilę. Drugi adres
        (`clients5`) jest rozliczany osobno, więc gdy pierwszy odmówi, próbujemy
        tam — dzięki temu tłumaczenie nie przerywa się w środku pracy.
        """
        source = to_lang_code(sl) or "auto"
        target = to_lang_code(tl)
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        last_error: Optional[Exception] = None

        for attempt, endpoint in enumerate(("gtx", "clients5")):
            try:
                if endpoint == "gtx":
                    params = urllib.parse.urlencode(
                        {"client": "gtx", "sl": source, "tl": target, "dt": "t", "q": text})
                    url = f"https://translate.googleapis.com/translate_a/single?{params}"
                    req = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                    return "".join(part[0] for part in data[0] if part and part[0])

                params = urllib.parse.urlencode(
                    {"client": "dict-chrome-ex", "sl": source, "tl": target, "q": text})
                url = f"https://clients5.google.com/translate_a/t?{params}"
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                # Odpowiedź bywa listą napisów albo zagnieżdżoną strukturą.
                if isinstance(data, list) and data:
                    if isinstance(data[0], str):
                        return "".join(data)
                    if isinstance(data[0], list):
                        return "".join(part[0] for part in data[0] if part and part[0])
                if isinstance(data, dict) and "sentences" in data:
                    return "".join(x.get("trans", "") for x in data["sentences"])
                raise RuntimeError("Nieznana odpowiedź serwera Google")
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code not in (429, 503):
                    raise
                # limit zapytań – krótka przerwa i próba drugiego adresu
                if attempt == 0:
                    time.sleep(0.6)
                    continue
                raise RuntimeError(
                    "Google odmawia dalszych tłumaczeń (limit zapytań na adres IP). "
                    "Odczekaj kilka minut albo użyj innego silnika, np. MyMemory."
                ) from exc
            except Exception as exc:
                last_error = exc
                if attempt == 0:
                    continue
                raise
        if last_error:
            raise last_error
        return ""

    # ---------------------------------------------------------- Microsoft
    #: Adres strony, z której pobieramy jednorazowy token dostępu Bing.
    BING_PAGE_URL = "https://www.bing.com/translator"
    #: Przeglądarkowy nagłówek – bez niego Bing zwraca stronę bez tokenów.
    BING_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0"
    )

    def _bing_session(self) -> dict:
        """Pobiera (i zapamiętuje) dane sesji darmowego tłumacza Bing.

        Strona www.bing.com/translator osadza w kodzie trzy wartości: identyfikator
        żądania ``IG``, identyfikator widoku ``IID`` oraz parę ``key``/``token``
        z zabezpieczenia przed nadużyciami. Token żyje ok. godziny, więc trzymamy
        go w pamięci i odświeżamy dopiero, gdy wygaśnie — dzięki temu jedno
        pobranie strony (ok. 600 kB) obsługuje setki segmentów.
        """
        session = getattr(self, "_bing_cache", None)
        if session and session.get("expires", 0) > time.time():
            return session

        # QuickTrans odpytuje silniki równolegle, a „Tłumacz wszystko” w pętli –
        # bez blokady kilka wątków pobierałoby tę samą stronę naraz (600 kB każdy).
        import threading

        lock = getattr(self, "_bing_lock", None)
        if lock is None:
            lock = self._bing_lock = threading.Lock()
        with lock:
            session = getattr(self, "_bing_cache", None)
            if session and session.get("expires", 0) > time.time():
                return session
            return self._fetch_bing_session()

    def _fetch_bing_session(self) -> dict:
        """Pobiera świeże tokeny ze strony tłumacza (wywoływane pod blokadą)."""
        import http.cookiejar

        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        request = urllib.request.Request(
            self.BING_PAGE_URL, headers={"User-Agent": self.BING_USER_AGENT})
        with opener.open(request, timeout=30) as response:
            html = response.read().decode("utf-8", "ignore")

        ig = re.search(r'IG:"([0-9A-F]+)"', html)
        iid = re.search(r'data-iid="([^"]+)"', html)
        params = re.search(r"params_AbusePreventionHelper\s*=\s*(\[.*?\])", html)
        if not (ig and iid and params):
            raise RuntimeError(
                "Microsoft Translator zmienił stronę – nie udało się pobrać sesji. "
                "Użyj innego silnika albo wpisz klucz Azure w Ustawieniach.")
        key, token, lifetime = json.loads(params.group(1))[:3]
        session = {
            "opener": opener,
            "ig": ig.group(1),
            "iid": iid.group(1),
            "key": str(key),
            "token": token,
            # margines 60 s, żeby nie trafić na token wygasający w locie
            "expires": time.time() + max(60, int(lifetime) / 1000 - 60),
        }
        self._bing_cache = session
        return session

    def _microsoft_free(self, text: str, sl: str, tl: str, _retry: bool = True) -> str:
        """Darmowy Microsoft Translator – ten sam silnik, co bing.com/translator.

        Nie wymaga klucza ani konta: program podszywa się pod przeglądarkę,
        pobiera jednorazowy token ze strony tłumacza i wysyła zapytanie tak,
        jak zrobiłaby to strona WWW. To ten sam model neuronowy, który stoi za
        płatnym Azure Translator, więc jakość jest znacznie wyższa niż MyMemory.
        """
        session = self._bing_session()
        source = to_lang_code(sl)
        payload = urllib.parse.urlencode({
            "fromLang": source if source and sl.lower() != "auto" else "auto-detect",
            "to": to_lang_code(tl),
            "text": text,
            "token": session["token"],
            "key": session["key"],
            "tryFetchingGenderDebiasedTranslations": "true",
        }).encode()
        url = (f"https://www.bing.com/ttranslatev3?isVertical=1&&IG={session['ig']}"
               f"&IID={session['iid']}")
        request = urllib.request.Request(url, data=payload, headers={
            "User-Agent": self.BING_USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": self.BING_PAGE_URL,
        })
        try:
            with session["opener"].open(request, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 403):
                raise RuntimeError(
                    "Microsoft (Bing) odmawia dalszych tłumaczeń – limit zapytań "
                    "na adres IP. Odczekaj chwilę albo użyj innego silnika."
                ) from exc
            raise

        # Wygasła sesja: serwer odpowiada słownikiem ze statusem, nie listą.
        if isinstance(data, dict):
            code = data.get("statusCode") or data.get("ShowCaptcha")
            if _retry:
                self._bing_cache = None
                return self._microsoft_free(text, sl, tl, _retry=False)
            raise RuntimeError(f"Microsoft odrzucił zapytanie (kod {code}).")
        if not data or not data[0].get("translations"):
            raise RuntimeError("Microsoft nie zwrócił tłumaczenia.")
        return data[0]["translations"][0]["text"]

    def _azure(self, text: str, sl: str, tl: str) -> str:
        """Azure AI Translator – oficjalne API Microsoftu (klucz z portalu Azure).

        Warstwa darmowa **F0** daje 2 000 000 znaków miesięcznie bez opłat
        (najwięcej ze wszystkich dostawców), ale wymaga konta Azure i utworzenia
        zasobu Translator. Kto nie chce zakładać konta – ma silnik
        „Microsoft Translator / Bing (bez klucza API)”, który używa tego samego modelu.
        """
        key = self.keys.get("azure_key", "").strip()
        if not key:
            raise RuntimeError(
                "Brak klucza Azure Translator. Warstwa darmowa F0 daje 2 mln znaków "
                "miesięcznie (portal.azure.com → Translator → F0). "
                "Bez konta użyj silnika „Microsoft Translator / Bing (bez klucza API)”.")
        endpoint = (self.keys.get("azure_endpoint")
                    or "https://api.cognitive.microsofttranslator.com").rstrip("/")
        region = self.keys.get("azure_region", "").strip()
        params = {"api-version": "3.0", "to": to_lang_code(tl)}
        if sl and sl.lower() != "auto":
            params["from"] = to_lang_code(sl)
        url = f"{endpoint}/translate?{urllib.parse.urlencode(params)}"
        headers = {
            "Ocp-Apim-Subscription-Key": key,
            "Content-Type": "application/json; charset=UTF-8",
        }
        if region:
            headers["Ocp-Apim-Subscription-Region"] = region
        body = json.dumps([{"Text": text}]).encode("utf-8")
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = json.loads(exc.read().decode()).get("error", {}).get("message", "")
            except Exception:
                pass
            if exc.code == 401:
                raise RuntimeError(
                    "Azure odrzucił klucz. Sprawdź klucz oraz region zasobu "
                    "(np. westeurope) w Ustawieniach → Tłumaczenie maszynowe.") from exc
            if exc.code == 403:
                raise RuntimeError(
                    "Azure: wyczerpany limit warstwy darmowej F0 (2 mln znaków/mies.) "
                    f"lub brak uprawnień. {detail}") from exc
            raise RuntimeError(f"Azure HTTP {exc.code}: {detail or exc.reason}") from exc
        return data[0]["translations"][0]["text"]

    # ------------------------------------------------------------ DeepL WWW
    #: Punkt, z którego korzysta strona deepl.com (nieoficjalny, bez klucza).
    DEEPL_WEB_URL = "https://www2.deepl.com/jsonrpc"
    #: Minimalny odstęp między zapytaniami – pomiar: przy 1 s połowa kończy
    #: się błędem 429, przy 5 s przechodzi 5 na 6. Wsad omija problem lepiej.
    DEEPL_WEB_MIN_INTERVAL = 5.0
    #: Po odmowie serwer blokuje adres IP na dłużej niż minutę (zmierzone:
    #: po 90 s nadal 429). Zapamiętujemy to, żeby nie zasypywać go zapytaniami
    #: i żeby od razu powiedzieć, ile trzeba odczekać.
    DEEPL_WEB_COOLDOWN = 300.0
    _deepl_web_blocked_until = 0.0

    def _deepl_web_request(self, texts: List[str], sl: str, tl: str) -> List[str]:
        """Wysyła jedno zapytanie do wewnętrznego API strony DeepL.

        Odtwarza dokładnie to, co robi przeglądarka na deepl.com: ten sam adres,
        te same nagłówki i dwie osobliwości protokołu, bez których serwer odrzuca
        żądanie — „timestamp” wyliczany z liczby liter *i* w tekście oraz spacja
        wstawiana po ``"method":`` dla części identyfikatorów.
        """
        import random
        import threading

        lock = getattr(self, "_deepl_web_lock", None)
        if lock is None:
            lock = self._deepl_web_lock = threading.Lock()

        joined = "".join(texts)
        stamp = int(time.time() * 1000)
        letters = joined.count("i") + 1
        stamp += letters - stamp % letters
        ident = random.randint(1000, 99999) * 1000

        payload = {
            "jsonrpc": "2.0",
            "method": "LMT_handle_texts",
            "id": ident,
            "params": {
                "texts": [{"text": t, "requestAlternatives": 0} for t in texts],
                "splitting": "newlines",
                "lang": {
                    "source_lang_user_selected": (to_lang_code(sl) or "auto").upper(),
                    "target_lang": to_lang_code(tl).upper(),
                },
                "timestamp": stamp,
                "commonJobParams": {"mode": "translate"},
            },
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        spaced = (ident + 5) % 29 == 0 or (ident + 3) % 13 == 0
        body = body.replace(b'"method":"',
                            b'"method" : "' if spaced else b'"method": "')

        request = urllib.request.Request(self.DEEPL_WEB_URL, data=body, headers={
            "User-Agent": self.BING_USER_AGENT,
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Origin": "https://www.deepl.com",
            "Referer": "https://www.deepl.com/",
        })

        # Odstęp jest pilnowany globalnie – równoległe wątki QuickTrans
        # inaczej wystrzeliłyby serię zapytań i od razu dostały 429.
        with lock:
            remaining = MachineTranslation._deepl_web_blocked_until - time.time()
            if remaining > 0:
                raise RuntimeError(self._deepl_web_blocked_message(remaining))

            last = getattr(self, "_deepl_web_last", 0.0)
            wait = self.DEEPL_WEB_MIN_INTERVAL - (time.time() - last)
            if wait > 0:
                time.sleep(wait)
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    data = json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    MachineTranslation._deepl_web_blocked_until = (
                        time.time() + self.DEEPL_WEB_COOLDOWN)
                    raise RuntimeError(
                        self._deepl_web_blocked_message(self.DEEPL_WEB_COOLDOWN)
                    ) from exc
                raise
            finally:
                self._deepl_web_last = time.time()

        if "error" in data:
            message = (data.get("error") or {}).get("message", "nieznany błąd")
            raise RuntimeError(f"DeepL (przez stronę): {message}")
        return [item.get("text", "") for item in data["result"]["texts"]]

    @staticmethod
    def _deepl_web_blocked_message(seconds: float) -> str:
        """Komunikat o blokadzie – z konkretnym czasem i alternatywą."""
        minutes = max(1, int(seconds // 60) + (1 if seconds % 60 else 0))
        return (
            f"DeepL przez stronę zablokował ten adres IP (limit zapytań). "
            f"Spróbuj ponownie za około {minutes} min.\n"
            "To nie jest oficjalne API — DeepL udostępnia stronę do ręcznego "
            "tłumaczenia, nie do pracy wsadowej, i szybko odcina automaty.\n"
            "Co teraz: użyj silnika „Microsoft Translator / Bing (bez klucza API)” "
            "— jakość jest zbliżona i nie ma takich limitów — albo wpisz darmowy "
            "klucz DeepL API Free (500 000 znaków/mies.) w Ustawieniach."
        )

    def deepl_web_ready(self) -> bool:
        """Czy DeepL przez stronę jest teraz dostępny (nie w blokadzie)."""
        return MachineTranslation._deepl_web_blocked_until <= time.time()

    def _deepl_web(self, text: str, sl: str, tl: str) -> str:
        """DeepL bez klucza – dokładnie tak, jak tłumaczy strona deepl.com.

        To **nieoficjalna** droga: program udaje przeglądarkę. Działa i daje
        jakość prawdziwego DeepL, ale limit zapytań na adres IP jest ostry,
        więc przy większych plikach lepiej sprawdza się tłumaczenie wsadowe
        (`translate_batch`) albo darmowy klucz DeepL API Free.
        """
        return self._deepl_web_request([text], sl, tl)[0]

    def _ibm_watson(self, text: str, sl: str, tl: str) -> str:
        key = self.keys.get("ibm_watson_key", "").strip()
        url = self.keys.get("ibm_watson_url", "").strip().rstrip("/")
        if not key or not url:
            raise RuntimeError("Brak klucza lub URL IBM Watson (Ustawienia → MT).")
        import base64

        auth = base64.b64encode(f"apikey:{key}".encode()).decode()
        payload = {"text": [text], "source": sl, "target": tl}
        headers = {"Authorization": f"Basic {auth}", "Content-Type": "application/json"}
        result = self._http_post(f"{url}/v3/translate?version=2018-05-01", json.dumps(payload).encode(), headers)
        return result["translations"][0]["translation"]

    def list_gemini_models(self, only_free_friendly: bool = True) -> List[str]:
        """Pobiera z API listę modeli dostępnych dla bieżącego klucza.

        Google wyłącza starsze modele dla nowych projektów, a nazwy zmieniają się
        co kilka miesięcy. Zamiast trzymać sztywną listę, pytamy API, co naprawdę
        działa dla tego konkretnego klucza.
        """
        key = self.keys.get("gemini", "").strip()
        if not key:
            raise RuntimeError("Najpierw wpisz klucz Gemini.")
        url = f"{GEMINI_BASE_URL}?pageSize=200"
        req = urllib.request.Request(url, headers={"x-goog-api-key": key})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:200]
            raise RuntimeError(f"Nie udało się pobrać listy modeli ({exc.code}): {body}")

        models: List[str] = []
        for item in data.get("models") or []:
            name = (item.get("name") or "").replace("models/", "")
            methods = item.get("supportedGenerationMethods") or []
            if not name or "generateContent" not in methods:
                continue
            if only_free_friendly and any(
                skip in name for skip in ("embedding", "aqa", "imagen", "veo", "tts", "image")
            ):
                continue
            models.append(name)
        # najpierw warianty „flash” – najlepszy stosunek jakości do limitów
        models.sort(key=lambda m: (0 if "flash" in m else 1, "preview" in m, m))
        return models

    def _gemini(self, text: str, sl: str, tl: str) -> str:
        """Google Gemini – klucz z Google AI Studio (bez karty płatniczej).

        Darmowy plan: ok. 10 zapytań/min i 250/dobę dla Gemini 2.5 Flash.
        Zużycie widać w liczniku (Narzędzia → Zużycie silników MT).
        """
        key = self.keys.get("gemini", "").strip()
        if not key:
            raise RuntimeError(
                "Brak klucza Gemini. Utwórz darmowy klucz na "
                "https://aistudio.google.com/apikey i wklej w Ustawienia → "
                "Tłumaczenie maszynowe."
            )
        model = self.keys.get("gemini_model") or GEMINI_DEFAULT_MODEL
        url = f"{GEMINI_BASE_URL}/{model}:generateContent"
        payload = {
            "system_instruction": {
                "parts": [{"text": build_translation_prompt(sl, tl, self.ai_instructions)}]
            },
            "contents": [{"role": "user", "parts": [{"text": text}]}],
            "generationConfig": {"temperature": 0.2},
        }
        headers = {"Content-Type": "application/json", "x-goog-api-key": key}
        try:
            result = self._http_post(url, json.dumps(payload).encode("utf-8"), headers, timeout=90)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:300]
            if exc.code == 429:
                raise RuntimeError(
                    "Przekroczono darmowy limit Gemini (10 zapytań/min, 250/dobę). "
                    "Poczekaj chwilę lub wybierz inny silnik."
                )
            if exc.code in (400, 401, 403):
                raise RuntimeError(f"Klucz Gemini odrzucony ({exc.code}). Sprawdź go w ustawieniach.")
            if exc.code == 404:
                # Model niedostępny dla tego konta (Google ogranicza starsze
                # modele do projektów z historią użycia). Znajdź działający
                # zamiennik i zapamiętaj go, żeby nie powtarzać próby.
                alt = self._pick_working_gemini_model(exclude=model)
                if alt:
                    self.keys["gemini_model"] = alt
                    self.save_keys()
                    return self._gemini(text, sl, tl)
                raise RuntimeError(
                    f"Model „{model}” nie jest dostępny dla tego klucza, a nie udało się "
                    "znaleźć zamiennika. Otwórz Ustawienia → MT i kliknij „Pobierz modele”."
                )
            raise RuntimeError(f"Gemini API {exc.code}: {body}")

        # zapamiętaj zużycie tokenów zgłoszone przez API
        meta = result.get("usageMetadata") or {}
        self._last_tokens = int(meta.get("totalTokenCount") or 0)

        candidates = result.get("candidates") or []
        if not candidates:
            feedback = result.get("promptFeedback") or {}
            raise RuntimeError(f"Brak odpowiedzi Gemini: {feedback or str(result)[:200]}")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        out = "".join(p.get("text", "") for p in parts).strip()
        if not out:
            raise RuntimeError("Gemini zwrócił pustą odpowiedź.")
        # Modele rozumujące potrafią dopisać cały tok myślenia – bierzemy sam wynik.
        return clean_ai_translation(out, text)

    def _pick_working_gemini_model(self, exclude: str = "") -> Optional[str]:
        """Wybiera model dostępny dla bieżącego klucza (po nieudanym 404)."""
        try:
            available = self.list_gemini_models()
        except Exception:
            available = []
        for candidate in GEMINI_MODELS:
            if candidate != exclude and candidate in available:
                return candidate
        for name in available:
            if name != exclude and "flash" in name:
                return name
        return available[0] if available and available[0] != exclude else None

    def _puter(self, text: str, sl: str, tl: str) -> str:
        """Puter AI Gateway – endpoint zgodny z OpenAI.

        Daje dostęp do modeli Gemma, GPT, Claude i innych. Wymaga darmowego
        tokenu z konta Puter (Ustawienia → MT → „Token Puter”), bo interfejs
        przeglądarkowy `puter.js` nie działa w aplikacji desktopowej.
        """
        token = self.keys.get("puter_token", "").strip()
        if not token:
            raise RuntimeError(
                "Brak tokenu Puter. Zaloguj się na puter.com, skopiuj token "
                "z ustawień konta i wklej w Ustawienia → Tłumaczenie maszynowe."
            )
        url = self.keys.get("puter_url") or PUTER_DEFAULT_URL
        model = self.keys.get("puter_model") or PUTER_DEFAULT_MODEL
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": build_translation_prompt(sl, tl, self.ai_instructions)},
                {"role": "user", "content": text},
            ],
            "temperature": 0.2,
        }
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            result = self._http_post(url, json.dumps(payload).encode("utf-8"), headers, timeout=90)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:200]
            if exc.code in (401, 403) or "reauth" in body:
                raise RuntimeError("Token Puter wygasł lub jest nieprawidłowy – zaloguj się ponownie.")
            raise RuntimeError(f"Puter API {exc.code}: {body}")
        choices = result.get("choices") or []
        if not choices:
            raise RuntimeError(str(result)[:200])
        usage = result.get("usage") or {}
        self._last_tokens = int(usage.get("total_tokens") or 0)
        message = choices[0].get("message") or {}
        return clean_ai_translation(message.get("content") or "", text)

    def _mymemory(self, text: str, sl: str, tl: str) -> str:
        """MyMemory – darmowe API, nie wymaga klucza (limit dzienny na adres IP)."""
        params = {"q": text, "langpair": f"{to_lang_code(sl)}|{to_lang_code(tl)}"}
        key = self.keys.get("mymemory", "").strip()
        if key:
            params["key"] = key
        email = self.keys.get("mymemory_email", "").strip()
        if email:  # podanie e-maila podnosi dzienny limit znaków
            params["de"] = email
        url = "https://api.mymemory.translated.net/get?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": "SuperCAT/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("responseStatus") in (200, "200"):
            return data["responseData"]["translatedText"]
        raise RuntimeError(data.get("responseDetails", "nieznany błąd MyMemory"))

    def translate_with(self, engine: str, text: str, sl: str, tl: str) -> str:
        """Tłumaczy wskazanym silnikiem, nie zmieniając silnika domyślnego.

        Bezpieczne w wielu wątkach — silnik idzie parametrem, więc równoległe
        wywołania QuickTrans nie wchodzą sobie w drogę.
        """
        return self.translate(text, sl, tl, engine=engine)

    def translate_multi(self, text: str, sl: str, tl: str,
                        engines: Optional[List[str]] = None,
                        timeout: float = 25.0) -> List[Tuple[str, str, str, bool]]:
        """Zbiorcze tłumaczenie: odpytuje kilka silników RÓWNOLEGLE.

        Zwraca listę krotek ``(kod, nazwa silnika, tłumaczenie, czy_błąd)``.
        Odpowiednik QuickTrans z Supervertaler Workbench – pozwala porównać
        propozycje kilku dostawców i wybrać najlepszą.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        engines = engines or self.available_engines()
        labels = dict(ENGINES)
        results: List[Tuple[str, str, str, bool]] = []

        def work(engine: str) -> Tuple[str, str, str, bool]:
            try:
                out = self.translate_with(engine, text, sl, tl)
                is_error = out.startswith("[Błąd MT")
                return (ENGINE_CODES.get(engine, "?"), labels.get(engine, engine), out, is_error)
            except Exception as exc:
                return (ENGINE_CODES.get(engine, "?"), labels.get(engine, engine), f"[Błąd: {exc}]", True)

        with ThreadPoolExecutor(max_workers=max(1, len(engines))) as pool:
            futures = {pool.submit(work, e): e for e in engines}
            for future in as_completed(futures, timeout=timeout):
                try:
                    results.append(future.result())
                except Exception as exc:
                    engine = futures[future]
                    results.append((ENGINE_CODES.get(engine, "?"), engine, f"[Błąd: {exc}]", True))

        order = {e: i for i, e in enumerate(engines)}
        results.sort(key=lambda r: (r[3], order.get(_code_to_engine(r[0], engines), 99)))
        return results

    def available_engines(self, only_free: bool = False) -> List[str]:
        """Silniki gotowe do użycia (darmowe zawsze, płatne gdy jest klucz)."""
        out: List[str] = []
        for engine, _label in ENGINES:
            if engine in ("local", "google_free", "microsoft_free",
                          "deepl_web", "mymemory"):
                out.append(engine)
            elif engine == "libretranslate" and self.keys.get("libretranslate_url"):
                out.append(engine)
            elif only_free:
                continue
            elif engine in ("deepl", "deepl_free") and self.keys.get("deepl"):
                out.append(engine)
            elif engine == "openai" and self.keys.get("openai"):
                out.append(engine)
            elif engine == "gemini" and self.keys.get("gemini"):
                out.append(engine)
            elif engine == "puter" and self.keys.get("puter_token"):
                out.append(engine)
            elif engine == "azure" and self.keys.get("azure_key"):
                out.append(engine)
            elif engine == "ibm_watson" and self.keys.get("ibm_watson_key"):
                out.append(engine)
            elif engine == "ai_offline" and self.keys.get("ai_offline_url"):
                out.append(engine)
        return out

    def quicktrans_engines(self, only_free: Optional[bool] = None) -> List[str]:
        """Silniki, które ma odpytać QuickTrans.

        Pusta lista w ustawieniach (``mt.quicktrans.engines``) oznacza „automatycznie”:
        wszystkie gotowe do użycia, z ewentualnym ograniczeniem do darmowych.
        Gdy użytkownik wskaże własny zestaw, ma on pierwszeństwo — pytamy dokładnie
        te silniki (o ile są skonfigurowane), niezależnie od przełącznika „bez klucza”.
        """
        settings = SettingsManager.instance()
        raw = settings.get_str("mt.quicktrans.engines", "")
        chosen = [item.strip() for item in raw.split(",") if item.strip()]
        available = self.available_engines(only_free=False)
        if chosen:
            picked = [engine for engine, _label in ENGINES
                      if engine in chosen and engine in available]
            if picked:
                return picked
        if only_free is None:
            only_free = settings.get_bool("mt.quicktrans.free_only", True)
        return self.available_engines(only_free=only_free)

    def _ai_offline(self, text: str, sl: str, tl: str) -> str:
        url = self.keys.get("ai_offline_url") or "http://localhost:8000/translate"
        payload = {"text": text, "source": sl, "target": tl}
        headers = {"Content-Type": "application/json"}
        result = self._http_post(url, json.dumps(payload).encode(), headers, timeout=120)
        for field in ("translation", "translatedText", "text", "result", "output"):
            if field in result:
                return str(result[field])
        return json.dumps(result, ensure_ascii=False)


def _code_to_engine(code: str, engines: List[str]) -> str:
    for engine in engines:
        if ENGINE_CODES.get(engine) == code:
            return engine
    return code


def _replace_ci(text: str, needle: str, replacement: str) -> str:
    import re

    return re.sub(rf"(?<!\w){re.escape(needle)}(?!\w)", replacement, text, flags=re.IGNORECASE)
