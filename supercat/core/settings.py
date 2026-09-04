"""Menedżer ustawień aplikacji (odpowiednik config/SettingsManager.java).

Ustawienia trzymane są w pliku JSON w katalogu użytkownika:
    ~/.supercat/settings.json
"""
from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict

APP_DIR = os.path.join(os.path.expanduser("~"), ".supercat")
SETTINGS_FILE = os.path.join(APP_DIR, "settings.json")

DEFAULTS: Dict[str, Any] = {
    # --- Pamięć tłumaczeniowa (TM) ---
    "fuzzy.threshold": 70,
    "tm.max.results": 10,
    "tm.adapt.tags": True,
    #: Podpowiedzi TM: dopasuj pozycje \\n/\\l/\\p do bieżącego segmentu.
    "tm.adapt.codes": True,
    # Kody do dopasowania są do wyboru — każda gra może używać innych
    # znaczników (np. \N, \L). Wpisane literalnie: backslash + znak.
    "tm.adapt.line.codes": "\\n \\l",
    "tm.adapt.para.codes": "\\p",
    #: Lista kodów gry — wklej kod po kodzie (np. \n, \l, {VAR}, <<TAG>>).
    # Jeśli pusta — kody są auto-detekowane z tekstu źródłowego.
    "tm.codes.list": "",
    "tm.filter.english": True,
    #: Nie zapisuj do TM wpisów, których tłumaczenie zostało po angielsku.
    "tm.reject.untranslated": False,
    "tm.sentence.matching.enabled": False,  # domyślnie wyłączone – bywa kosztowne
    "tm.sentence.line.threshold": 65,
    "tm.sentence.max.units": 20000,       # powyżej tylu wpisów pomijaj dopasowanie zdań
    "tm.sentence.auto.insert": False,     # wstawiaj najlepsze złożenie automatycznie
    "tm.sentence.auto.threshold": 90,      # próg dopasowania linii (dopasowanie zdań)
    "tm.sentence.use.translated": False,    # bierz też segmenty przetłumaczone w projekcie
    "tm.auto.export.enabled": False,
    "tm.auto.export.folder": "",
    "tm.autosave.tmx": True,              # zapisuj pamięć projektu do pliku TMX
    "tm.autosave.tmx.name": "project_tm.tmx",
    # --- Edytor ---
    "editor.font.size": 12,
    "ui.time.unit": "auto",               # auto | ms | s | min – jednostki licznika czasu
    "editor.font.family": "Segoe UI",
    "editor.wrap.text": True,
    "editor.highlight.current": True,
    "editor.ignore.metadata": True,
    "editor.ignore.patterns": "<<< FILE:,<<KON>>",
    # --- Auto-zapis ---
    "auto.save.enabled": True,
    "auto.save.interval": 30,
    # --- Motyw ---
    "theme.dark": True,
    # --- Projekt ---
    "auto.load.last.project": False,
    "last.project.path": "",
    # --- Glosariusz ---
    "glossary.highlight": True,
    "glossary.auto.suggest": True,
    # --- Auto-wstawianie ---
    "auto.insert.enabled": True,
    "auto.insert.threshold": 80,
    "auto.insert.overwrite": False,
    "tm.lookup.enabled": True,
    "tm.auto.add": True,
    "editor.confirm.status": "translated",
    #: Strzałki ↑/↓ w polu tłumaczenia przechodzą między segmentami,
    #: gdy kursor jest w pierwszym/ostatnim wierszu tekstu.
    "editor.arrows.change.segment": True,
    "editor.confirm.skip.done": True,
    "auto.apply.on.load": False,          # zastosuj TM zaraz po wczytaniu plików
    "auto.apply.on.load.threshold": 80,   # próg dla automatycznego uzupełniania
    "auto.mt.on.load": False,             # przetłumacz maszynowo resztę po wczytaniu
    "auto.load.confirm": True,            # pytaj przed automatycznym uzupełnianiem
    # --- QA ---
    "qa.check.numbers": True,
    "qa.check.tags": True,
    "qa.check.consistency": True,
    "qa.check.length": True,
    "qa.check.punctuation": True,
    "qa.check.capitalization": True,
    "qa.check.empty": True,
    # --- Eksport ---
    "export.include.segment.id": True,
    "export.include.notes": False,
    # --- Tłumaczenie maszynowe ---
    "mt.engine": "local",                 # silnik dla pojedynczego segmentu (Ctrl+M)
    "mt.batch.engine": "",
    "mt.translate.by.line": True,
    "mt.ai.instructions": "",             # własne wytyczne dla modeli AI         # tłumacz każdą linię (\n, \p) osobno                # silnik operacji zbiorczych ("" = jak wyżej)
    "mt.quicktrans.engines": "",          # silniki QuickTrans ("" = wszystkie dostępne)
    "mt.quicktrans.free_only": True,
    "editor.engine.free_only": False,     # lista silników w edytorze: tylko darmowe
    "mt.azure.key": "",
    "mt.azure.region": "",
    "mt.deepl.api.key": "",
    "mt.deepl.formality": "default",
    "mt.deepl.web.fallback": True,        # gdy DeepL WWW zablokowany → Microsoft
    "mt.openai.api.key": "",
    "mt.openai.model": "gpt-4o-mini",
    "mt.openai.url": "https://api.openai.com/v1/chat/completions",
    "mt.libretranslate.url": "http://localhost:5000",
    "mt.libretranslate.key": "",
    "mt.ibm.watson.key": "",
    "mt.ibm.watson.url": "",
    "mt.ai.offline.url": "http://localhost:8000/translate",
}


class SettingsManager:
    """Singleton z ustawieniami aplikacji."""

    _instance: "SettingsManager | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._data: Dict[str, Any] = dict(DEFAULTS)
        self.load()

    @classmethod
    def instance(cls) -> "SettingsManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = SettingsManager()
        return cls._instance

    # ------------------------------------------------------------------
    def load(self) -> None:
        try:
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, "r", encoding="utf-8") as fh:
                    stored = json.load(fh)
                if isinstance(stored, dict):
                    self._data.update(stored)
        except Exception as exc:  # pragma: no cover - defensywnie
            print(f"⚠️ Nie udało się wczytać ustawień: {exc}")

    def save(self) -> None:
        try:
            os.makedirs(APP_DIR, exist_ok=True)
            with open(SETTINGS_FILE, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, ensure_ascii=False, indent=2)
        except Exception as exc:  # pragma: no cover
            print(f"⚠️ Nie udało się zapisać ustawień: {exc}")

    # ------------------------------------------------------------------
    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self.save()

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, DEFAULTS.get(key, default))

    def get_str(self, key: str, default: str = "") -> str:
        value = self.get(key, default)
        return "" if value is None else str(value)

    def get_int(self, key: str, default: int = 0) -> int:
        try:
            return int(self.get(key, default))
        except (TypeError, ValueError):
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        value = self.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "tak", "yes")
        return bool(value)

    def all(self) -> Dict[str, Any]:
        return dict(self._data)

    def reset_to_defaults(self) -> None:
        self._data = dict(DEFAULTS)
        self.save()
