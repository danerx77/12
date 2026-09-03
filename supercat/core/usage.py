"""Licznik zużycia silników tłumaczenia maszynowego.

Śledzi liczbę zapytań i tokenów per silnik, z podziałem na dzień i ostatnią
minutę. Dzięki temu widać, ile z darmowego limitu (np. Gemini: 10 zapytań/min,
250/dobę) zostało wykorzystane, zanim serwer zwróci błąd 429.

Dane trzymane są w ~/.supercat/usage.json, więc licznik przeżywa restart
programu — inaczej po ponownym uruchomieniu pokazywałby zero, mimo że limit
u dostawcy nadal jest naliczony.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional

from .settings import APP_DIR

USAGE_FILE = os.path.join(APP_DIR, "usage.json")

#: Znane limity darmowych planów: (zapytań/minutę, zapytań/dobę).
#: None = brak znanego limitu (własny serwer, silnik lokalny itp.).
KNOWN_LIMITS: Dict[str, tuple] = {
    "gemini": (10, 250),        # Google AI Studio – darmowy plan
    "mymemory": (None, 1000),   # limit znakowy, orientacyjnie
    "google_free": (None, None),
    "deepl_free": (None, None),
    "puter": (None, None),      # model „User-Pays” – limity konta użytkownika
    "local": (None, None),
}


@dataclass
class EngineUsage:
    """Zużycie pojedynczego silnika."""

    requests_today: int = 0
    tokens_today: int = 0
    chars_today: int = 0
    errors_today: int = 0
    requests_total: int = 0
    tokens_total: int = 0
    last_used: float = 0.0
    #: znaczniki czasu ostatnich zapytań (do liczenia zapytań na minutę)
    recent: List[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        data = self.__dict__.copy()
        data["recent"] = []          # znaczniki czasu nie mają sensu po restarcie
        return data


class UsageTracker:
    """Singleton zbierający statystyki użycia silników MT."""

    _instance: "UsageTracker | None" = None
    _lock = threading.RLock()

    def __init__(self) -> None:
        self.day: str = date.today().isoformat()
        self.engines: Dict[str, EngineUsage] = {}
        self._load()

    @classmethod
    def instance(cls) -> "UsageTracker":
        with cls._lock:
            if cls._instance is None:
                cls._instance = UsageTracker()
        return cls._instance

    # ------------------------------------------------------------------
    def _load(self) -> None:
        try:
            if not os.path.exists(USAGE_FILE):
                return
            with open(USAGE_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            stored_day = data.get("day", "")
            for name, values in (data.get("engines") or {}).items():
                usage = EngineUsage()
                for key, value in values.items():
                    if hasattr(usage, key):
                        setattr(usage, key, value)
                self.engines[name] = usage
            # nowy dzień – wyzeruj liczniki dobowe, zachowaj sumy całkowite
            if stored_day != self.day:
                self.reset_day(keep_totals=True)
        except Exception as exc:  # pragma: no cover
            print(f"⚠️ Nie udało się wczytać licznika zużycia: {exc}")

    def _save(self) -> None:
        try:
            os.makedirs(APP_DIR, exist_ok=True)
            payload = {
                "day": self.day,
                "engines": {k: v.to_dict() for k, v in self.engines.items()},
            }
            with open(USAGE_FILE, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=1)
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _rollover_if_needed(self) -> None:
        today = date.today().isoformat()
        if today != self.day:
            self.day = today
            self.reset_day(keep_totals=True)

    def get(self, engine: str) -> EngineUsage:
        with self._lock:
            self._rollover_if_needed()
            if engine not in self.engines:
                self.engines[engine] = EngineUsage()
            return self.engines[engine]

    def record(self, engine: str, *, chars: int = 0, tokens: int = 0,
               error: bool = False) -> None:
        """Zapisuje jedno wywołanie silnika."""
        with self._lock:
            usage = self.get(engine)
            now = time.time()
            usage.requests_today += 1
            usage.requests_total += 1
            usage.chars_today += max(0, chars)
            usage.tokens_today += max(0, tokens)
            usage.tokens_total += max(0, tokens)
            usage.last_used = now
            if error:
                usage.errors_today += 1
            usage.recent.append(now)
            cutoff = now - 60
            usage.recent = [t for t in usage.recent if t >= cutoff]
            self._save()

    def requests_last_minute(self, engine: str) -> int:
        with self._lock:
            usage = self.get(engine)
            cutoff = time.time() - 60
            usage.recent = [t for t in usage.recent if t >= cutoff]
            return len(usage.recent)

    # ------------------------------------------------------------------
    def limits(self, engine: str) -> tuple:
        return KNOWN_LIMITS.get(engine, (None, None))

    def summary(self, engine: str) -> str:
        """Krótki opis zużycia do paska stanu."""
        usage = self.get(engine)
        rpm_limit, rpd_limit = self.limits(engine)
        parts = []
        rpm = self.requests_last_minute(engine)
        if rpm_limit:
            parts.append(f"{rpm}/{rpm_limit} na min")
        elif rpm:
            parts.append(f"{rpm}/min")
        if rpd_limit:
            parts.append(f"{usage.requests_today}/{rpd_limit} dziś")
        else:
            parts.append(f"{usage.requests_today} dziś")
        if usage.tokens_today:
            parts.append(f"{usage.tokens_today:,} tok.".replace(",", " "))
        return " • ".join(parts)

    def percent_used(self, engine: str) -> Optional[int]:
        """Procent wykorzystania limitu dobowego (None, gdy brak limitu)."""
        usage = self.get(engine)
        _rpm, rpd = self.limits(engine)
        if not rpd:
            return None
        return min(100, int(usage.requests_today * 100 / rpd))

    def is_near_limit(self, engine: str) -> bool:
        pct = self.percent_used(engine)
        return pct is not None and pct >= 80

    def report(self) -> List[dict]:
        """Pełne zestawienie do okna statystyk."""
        with self._lock:
            self._rollover_if_needed()
            rows = []
            for name, usage in sorted(self.engines.items()):
                rpm_limit, rpd_limit = self.limits(name)
                rows.append({
                    "engine": name,
                    "requests_today": usage.requests_today,
                    "requests_total": usage.requests_total,
                    "tokens_today": usage.tokens_today,
                    "tokens_total": usage.tokens_total,
                    "chars_today": usage.chars_today,
                    "errors_today": usage.errors_today,
                    "rpm": self.requests_last_minute(name),
                    "rpm_limit": rpm_limit,
                    "rpd_limit": rpd_limit,
                    "percent": self.percent_used(name),
                    "last_used": usage.last_used,
                })
            return rows

    def reset_day(self, keep_totals: bool = True) -> None:
        with self._lock:
            for usage in self.engines.values():
                usage.requests_today = 0
                usage.tokens_today = 0
                usage.chars_today = 0
                usage.errors_today = 0
                usage.recent = []
                if not keep_totals:
                    usage.requests_total = 0
                    usage.tokens_total = 0
            self.day = date.today().isoformat()
            self._save()

    def reset_all(self) -> None:
        with self._lock:
            self.engines.clear()
            self.day = date.today().isoformat()
            self._save()
