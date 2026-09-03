"""Zadania działające w tle (QThread), żeby interfejs nie zamarzał.

* `TMLookupWorker`      – wyszukiwanie dopasowań dla bieżącego segmentu
* `PreTranslateWorker`  – masowe uzupełnianie tłumaczeń z TM („Zastosuj TM”)
* `MTWorker`            – tłumaczenie maszynowe wielu segmentów
* `TMXImportWorker`     – import dużych plików TMX
* `DictionaryDownloadWorker` – pobieranie słowników Hunspell
* `LangCheckWorker`     – kontrola poprawności językowej tłumaczenia
* `LTDownloadWorker`    – pobieranie silnika LanguageTool offline
* `LTTestWorker`        – test działania LanguageTool
* `LTInstallWorker`     – instalacja pakietu LibreTranslate
* `LTStartWorker`       – uruchamianie lokalnego serwera LibreTranslate
"""
from __future__ import annotations

import time

from typing import List, Optional, Sequence

from PyQt6.QtCore import QThread, pyqtSignal

from ..core.tm import SentenceMatch, TranslationMatch


class TMWarmupWorker(QThread):
    """Buduje indeksy pamięci w tle, zaraz po otwarciu projektu.

    Dzięki temu pierwsze wyszukiwanie nie płaci jednorazowego kosztu budowy
    indeksu (setki ms przy dużych pamięciach) w trakcie pracy użytkownika.
    """

    finished_warmup = pyqtSignal(int)

    def __init__(self, tm, parent=None) -> None:
        super().__init__(parent)
        self.tm = tm
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        count = 0
        try:
            self.tm._ensure_index()
            if not self._cancelled:
                self.tm._index.build_word_index()
            if not self._cancelled:
                self.tm._index.length_array()
            if not self._cancelled:
                # rozgrzej też cache linii dla dopasowania zdań
                self.tm.find_sentence_matches(
                    "warm up cache", should_cancel=lambda: self._cancelled
                )
            count = self.tm.size()
        except Exception as exc:
            print(f"⚠️ TMWarmupWorker: {exc}")
        self.finished_warmup.emit(count)


class TMLookupWorker(QThread):
    """Szuka dopasowań TM dla jednego segmentu poza wątkiem interfejsu."""

    finished_lookup = pyqtSignal(int, list, list, dict)  # (index, fuzzy, sentence, czasy)

    def __init__(self, tm, source: str, index: int, threshold: int, limit: int,
                 sentence_matching: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.tm = tm
        self.source = source
        self.index = index
        self.threshold = threshold
        self.limit = limit
        self.sentence_matching = sentence_matching
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        import time as _t

        fuzzy: List[TranslationMatch] = []
        sentences: List[SentenceMatch] = []
        timing = {"fuzzy_ms": 0.0, "sentence_ms": 0.0, "total_ms": 0.0}
        started = _t.perf_counter()
        try:
            t0 = _t.perf_counter()
            fuzzy = self.tm.find_fuzzy_matches(self.source, self.threshold, self.limit)
            timing["fuzzy_ms"] = (_t.perf_counter() - t0) * 1000
            if self.sentence_matching and not self._cancelled:
                # przekazujemy test przerwania – gdy użytkownik przejdzie dalej,
                # wyszukiwanie kończy się od razu i nie obciąża procesora
                t0 = _t.perf_counter()
                sentences = self.tm.find_sentence_matches(
                    self.source, should_cancel=lambda: self._cancelled
                )
                timing["sentence_ms"] = (_t.perf_counter() - t0) * 1000
        except Exception as exc:  # baza mogła zostać zamknięta w trakcie
            print(f"⚠️ TMLookupWorker: {exc}")
        timing["total_ms"] = (_t.perf_counter() - started) * 1000
        if not self._cancelled:
            self.finished_lookup.emit(self.index, fuzzy, sentences, timing)


class PreTranslateWorker(QThread):
    """Uzupełnia puste segmenty dopasowaniami z TM (wsadowo, w tle)."""

    progress = pyqtSignal(int, int)          # (zrobione, wszystkie)
    finished_batch = pyqtSignal(list, list)  # (indeksy segmentów, dopasowania)

    def __init__(self, tm, sources: Sequence[str], indices: Sequence[int],
                 threshold: int, parent=None) -> None:
        super().__init__(parent)
        self.tm = tm
        self.sources = list(sources)
        self.indices = list(indices)
        self.threshold = threshold
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        def on_progress(done: int, total: int) -> bool:
            self.progress.emit(done, total)
            return not self._cancelled

        try:
            matches = self.tm.find_best_matches_batch(self.sources, self.threshold, on_progress)
        except Exception as exc:
            print(f"⚠️ PreTranslateWorker: {exc}")
            matches = []
        self.finished_batch.emit(self.indices, matches)


class MTWorker(QThread):
    """Tłumaczenie maszynowe wielu segmentów w tle."""

    progress = pyqtSignal(int, int, str)
    translated = pyqtSignal(int, str)
    finished_all = pyqtSignal(int)

    def __init__(self, mt, sources: Sequence[str], indices: Sequence[int],
                 source_lang: str, target_lang: str, engine: Optional[str] = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.mt = mt
        self.sources = list(sources)
        self.indices = list(indices)
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.engine = engine  # None => silnik domyślny z ustawień
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        engine = self.engine or self.mt.engine
        if engine == "deepl_web":
            self._run_batched(engine)
            return

        done = 0
        total = len(self.sources)
        for pos, (idx, source) in enumerate(zip(self.indices, self.sources)):
            if self._cancelled:
                break
            self.progress.emit(pos, total, source[:60])
            try:
                if self.engine:
                    result = self.mt.translate_with(self.engine, source, self.source_lang, self.target_lang)
                else:
                    result = self.mt.translate(source, self.source_lang, self.target_lang)
            except Exception as exc:
                result = f"[Błąd MT: {exc}]"
            self.translated.emit(idx, result)
            done += 1
        self.finished_all.emit(done)

    def _run_batched(self, engine: str) -> None:
        """DeepL przez stronę: paczkami, bo pojedyncze zapytania łapią limit.

        Jedno zapytanie obsługuje kilkanaście segmentów w niecałą sekundę,
        więc cały plik przechodzi bez błędu 429.
        """
        size = getattr(self.mt, "DEEPL_WEB_BATCH", 10)
        done = 0
        total = len(self.sources)
        for start in range(0, total, size):
            if self._cancelled:
                break
            chunk = self.sources[start:start + size]
            indices = self.indices[start:start + size]
            self.progress.emit(
                start, total, f"paczka {start // size + 1}: {chunk[0][:50]}")
            try:
                results = self.mt.translate_batch(
                    chunk, self.source_lang, self.target_lang, engine=engine)
            except Exception as exc:
                results = [f"[Błąd MT: {exc}]"] * len(chunk)
            for idx, result in zip(indices, results):
                self.translated.emit(idx, result)
                done += 1
        self.finished_all.emit(done)


class TMXImportWorker(QThread):
    """Import pliku TMX w tle (duże pliki nie blokują okna)."""

    progress = pyqtSignal(int)
    finished_import = pyqtSignal(int, str)  # (liczba wpisów, komunikat błędu)

    def __init__(self, tm, path: str, parent=None) -> None:
        super().__init__(parent)
        self.tm = tm
        self.path = path

    def run(self) -> None:
        try:
            count = self.tm.import_tmx(self.path, lambda p: self.progress.emit(p))
            self.finished_import.emit(count, "")
        except Exception as exc:
            self.finished_import.emit(0, str(exc))


class DictionaryDownloadWorker(QThread):
    """Pobiera plik słownika w tle – okno nie zamiera na czas transferu."""

    progress = pyqtSignal(int, int)        # (pobrane bajty, całość lub 0)
    finished_download = pyqtSignal(str, str)   # (ścieżka, komunikat błędu)

    def __init__(self, url: str, target_path: str, parent=None,
                 extra_url: str = "", extra_path: str = "") -> None:
        super().__init__(parent)
        self.url = url
        self.target_path = target_path
        #: Plik towarzyszący (.aff) – deklaruje kodowanie słownika.
        #: Jego brak nie jest błędem, więc pobieramy go „na próbę”.
        self.extra_url = extra_url
        self.extra_path = extra_path
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        from ..core.glossary import Dictionary

        try:
            Dictionary.download(
                self.url, self.target_path,
                on_progress=lambda done, total: self.progress.emit(done, total),
                should_cancel=lambda: self._cancelled,
            )
            if self.extra_url and self.extra_path and not self._cancelled:
                try:
                    Dictionary.download(self.extra_url, self.extra_path)
                except Exception:
                    pass        # .aff bywa niedostępny – kodowanie wykryjemy sami
            self.finished_download.emit(self.target_path, "")
        except InterruptedError:
            self.finished_download.emit("", "Pobieranie przerwane")
        except Exception as exc:
            self.finished_download.emit("", str(exc))


class LangCheckWorker(QThread):
    """Sprawdza język tłumaczenia poza wątkiem interfejsu.

    LanguageTool działa przez sieć, więc bez wątku okno zamierałoby
    na czas zapytania.
    """

    finished_check = pyqtSignal(int, list, str)   # (indeks segmentu, uwagi, błąd)

    def __init__(self, text: str, index: int, dictionary=None,
                 use_languagetool: bool = False, client=None, parent=None) -> None:
        super().__init__(parent)
        self.text = text
        self.index = index
        self.dictionary = dictionary
        self.use_languagetool = use_languagetool
        self.client = client
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        from ..core.langcheck import check_translation

        try:
            from ..core.langcheck import options_from_settings

            issues, error = check_translation(
                self.text, self.dictionary, self.use_languagetool, self.client,
                options=options_from_settings())
        except Exception as exc:
            issues, error = [], str(exc)
        if not self._cancelled:
            self.finished_check.emit(self.index, issues, error)


class SuggestionWorker(QThread):
    """Dolicza propozycje pisowni w tle.

    Hunspell potrzebuje ok. sekundy na wyraz, więc liczenie propozycji od razu
    blokowałoby panel na kilka sekund. Podkreślenia pokazujemy natychmiast,
    a listę propozycji uzupełniamy chwilę później.
    """

    finished_suggestions = pyqtSignal(int, list)   # (indeks segmentu, uwagi)

    def __init__(self, issues: list, dictionary, index: int, parent=None) -> None:
        super().__init__(parent)
        self.issues = issues
        self.dictionary = dictionary
        self.index = index
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        from ..core.langcheck import fill_suggestions

        # Dwa przebiegi: najpierw szybkie dopasowanie (~0,1 s na wyraz), żeby
        # użytkownik od razu miał jakieś propozycje, potem dokładny Hunspell.
        try:
            if fill_suggestions(self.issues, self.dictionary,
                                should_cancel=lambda: self._cancelled, fast=True):
                if not self._cancelled:
                    self.finished_suggestions.emit(self.index, self.issues)
        except Exception:
            pass

        if self._cancelled or not getattr(self.dictionary, "has_morphology", False):
            return
        try:
            for issue in self.issues:
                if self._cancelled:
                    return
                if issue.rule_id != "PISOWNIA" or not issue.fragment:
                    continue
                better = self.dictionary.suggest_corrections(issue.fragment, 5)
                if better:
                    issue.suggestions = better
        except Exception:
            pass
        if not self._cancelled:
            self.finished_suggestions.emit(self.index, self.issues)


class LTDownloadWorker(QThread):
    """Pobiera silnik LanguageTool offline (~230 MB) w tle, z postępem w %."""

    progress = pyqtSignal(int, int)             # (pobrane bajty, całość lub 0)
    finished_download = pyqtSignal(bool, str)   # (sukces, komunikat błędu)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._last_emit = 0.0

    def _on_progress(self, done: int, total: int) -> None:
        # Sygnał wysyłamy najwyżej co 100 ms – przy 230 MB i porcjach po kilka
        # kilobajtów zalałby wątek interfejsu dziesiątkami tysięcy zdarzeń.
        import time

        now = time.monotonic()
        if now - self._last_emit >= 0.1 or (total and done >= total):
            self._last_emit = now
            self.progress.emit(int(done), int(total))

    def run(self) -> None:
        from ..core.langcheck import LocalLanguageTool

        ok, message = LocalLanguageTool.download_engine(on_progress=self._on_progress)
        self.finished_download.emit(ok, message)


class LTTestWorker(QThread):
    """Sprawdza działanie LanguageTool (offline albo przez sieć) poza wątkiem GUI."""

    finished_test = pyqtSignal(bool, int, str)   # (sukces, liczba uwag, błąd)

    def __init__(self, local: bool, url: str = "", parent=None) -> None:
        super().__init__(parent)
        self.local = local
        self.url = url

    def run(self) -> None:
        from ..core.langcheck import LanguageToolClient, LocalLanguageTool

        try:
            if self.local:
                tool = LocalLanguageTool.instance()
            else:
                tool = LanguageToolClient(url=self.url or None)
            issues = tool.check("Dziekuje za pomoc , kolego.")
            self.finished_test.emit(not tool.last_error, len(issues), tool.last_error)
        except Exception as exc:
            self.finished_test.emit(False, 0, str(exc))


class LTInstallWorker(QThread):
    """Instaluje pakiet LibreTranslate w tle (pip potrafi trwać minuty)."""

    output = pyqtSignal(str)
    progress = pyqtSignal(int, str)      # (procent lub -1, opis)
    finished_install = pyqtSignal(bool, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        from ..core.libretranslate_setup import install

        ok, message = install(on_output=self.output.emit,
                              cancelled=lambda: self._cancelled,
                              on_progress=lambda p, t: self.progress.emit(p, t))
        self.finished_install.emit(ok, message)


class LTStartWorker(QThread):
    """Uruchamia lokalny serwer LibreTranslate i czeka, aż odpowie."""

    output = pyqtSignal(str)
    finished_start = pyqtSignal(bool, str)

    #: Postęp pobierania modeli: (pobrane bajty, wszystkie bajty).
    bytes_progress = pyqtSignal(int, int)

    def __init__(self, server, languages: str = "en,pl", parent=None) -> None:
        super().__init__(parent)
        self.server = server
        self.languages = languages
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        """Najpierw pobiera modele (z prawdziwym postępem), potem startuje serwer.

        Argos ściąga model w całości do pamięci i zapisuje jednym `write` na
        końcu, więc obserwowanie katalogu nic nie dawało — pasek stał w miejscu
        przez kilka minut. Pobieranie robimy więc sami, kawałkami po 256 kB.
        """
        from ..core.libretranslate_setup import ensure_models

        ok, message = ensure_models(
            self.languages,
            on_output=self.output.emit,
            on_bytes=lambda done, total: self.bytes_progress.emit(done, total),
            cancelled=lambda: self._cancelled,
        )
        if not ok:
            self.finished_start.emit(False, message)
            return
        ok, message = self.server.start(self.languages, on_output=self.output.emit)
        self.finished_start.emit(ok, message)
