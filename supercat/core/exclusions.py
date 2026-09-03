"""Reguły wykluczania segmentów z tłumaczenia i ze statystyk.

W plikach gier obok tekstu do tłumaczenia występują wiersze techniczne::

    <<< FILE: CeladonCity_Condominiums_RoofRoom/text.inc >>>
    #org @8005A2
    [POKEMON_NAME]

Takie segmenty nie powinny trafiać do tłumaczenia maszynowego, do pamięci TM
ani do statystyk „ile zostało do zrobienia”. Moduł pozwala opisać je regułami,
z których każda ma własny typ dopasowania i można ją osobno włączyć lub wyłączyć.

Zasada bezpieczeństwa: wykluczenie **nie usuwa** segmentu — jest oznaczany jako
pominięty, więc treść zostaje w pliku i wraca przy eksporcie bez zmian.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

#: Typy dopasowania dostępne w regule.
MATCH_TYPES = {
    "contains": "zawiera tekst",
    "starts": "zaczyna się od",
    "ends": "kończy się na",
    "exact": "jest dokładnie równy",
    "wildcard": "wzorzec z gwiazdką (*)",
    "range": "zakres numerowany (TM01-TM66)",
    "regex": "wyrażenie regularne",
}

DEFAULT_MATCH = "wildcard"


@dataclass
class ExclusionRule:
    """Pojedyncza reguła wykluczająca segment z tłumaczenia."""

    pattern: str
    match_type: str = DEFAULT_MATCH
    enabled: bool = True
    case_sensitive: bool = False
    #: Opis pokazywany użytkownikowi (do czego służy reguła).
    comment: str = ""
    #: Nazwa pliku, którego reguła dotyczy (pusta = wszystkie pliki).
    file_filter: str = ""

    def to_dict(self) -> dict:
        return {
            "pattern": self.pattern,
            "match_type": self.match_type,
            "enabled": self.enabled,
            "case_sensitive": self.case_sensitive,
            "comment": self.comment,
            "file_filter": self.file_filter,
        }

    @staticmethod
    def from_dict(data: dict) -> "ExclusionRule":
        return ExclusionRule(
            pattern=data.get("pattern", ""),
            match_type=data.get("match_type", DEFAULT_MATCH),
            enabled=bool(data.get("enabled", True)),
            case_sensitive=bool(data.get("case_sensitive", False)),
            comment=data.get("comment", ""),
            file_filter=data.get("file_filter", ""),
        )

    def describe(self) -> str:
        label = MATCH_TYPES.get(self.match_type, self.match_type)
        out = f"{label}: „{self.pattern}”"
        if self.match_type == "range":
            count = len(expand_ranges(self.pattern))
            if count > 1:
                out += f"  ({count} pozycji)"
        if self.file_filter:
            out += f"  (tylko {self.file_filter})"
        if self.comment:
            out += f"  — {self.comment}"
        return out

    # ------------------------------------------------------------------
    def compiled(self) -> Optional[re.Pattern]:
        """Zwraca skompilowany wzorzec albo None, gdy reguła jest niepoprawna."""
        if not self.pattern:
            return None
        flags = 0 if self.case_sensitive else re.IGNORECASE
        try:
            if self.match_type == "regex":
                return re.compile(self.pattern, flags)
            if self.match_type == "wildcard":
                # Gwiazdka zastępuje dowolny ciąg – wygodniejsza niż pełny regex.
                parts = [re.escape(p) for p in self.pattern.split("*")]
                return re.compile(".*".join(parts), flags)
            if self.match_type == "range":
                # „TM01-TM66” → jedna reguła zamiast 66 osobnych wpisów.
                # Granice \b pilnują, żeby TM1 nie łapało TM10.
                names = expand_ranges(self.pattern)
                joined = "|".join(re.escape(n) for n in names)
                return re.compile(rf"\b(?:{joined})\b", flags)
            escaped = re.escape(self.pattern)
            if self.match_type == "starts":
                return re.compile(r"^\s*" + escaped, flags)
            if self.match_type == "ends":
                return re.compile(escaped + r"\s*$", flags)
            if self.match_type == "exact":
                return re.compile(r"^\s*" + escaped + r"\s*$", flags)
            return re.compile(escaped, flags)          # contains
        except re.error:
            return None

    def matches(self, text: str, file_name: str = "") -> bool:
        """Czy reguła obejmuje ten segment?"""
        if not self.enabled or not self.pattern:
            return False
        if self.file_filter and self.file_filter != (file_name or ""):
            return False
        pattern = self.compiled()
        if pattern is None:
            return False
        return pattern.search(text or "") is not None

    def error(self) -> str:
        """Komunikat, gdy wzorca nie da się skompilować (pusty = wszystko OK)."""
        if not self.pattern:
            return "Pusty wzorzec"
        if self.compiled() is None:
            return "Błędne wyrażenie regularne"
        return ""


#: Wersja zestawu reguł wbudowanych. Projekty zapisane starszą wersją
#: (bez tego pola) dostają brakujące reguły przy pierwszym odczycie.
BUILTIN_VERSION = 1

#: Gotowe reguły dla plików gier – proponowane przy pierwszym uruchomieniu.
#: Zakresy Unicode pisma CJK: japoński (hiragana, katakana), chiński (hanzi),
#: koreański (hangul) oraz japońska interpunkcja i pełnej szerokości spacja.
_CJK_RANGES = (
    (0x3000, 0x303F),    # interpunkcja CJK: 、。「」　(pełnej szerokości spacja)
    (0x3040, 0x309F),    # hiragana:  ひらがな
    (0x30A0, 0x30FF),    # katakana:  カタカナ
    (0x3400, 0x4DBF),    # hanzi – rozszerzenie A
    (0x4E00, 0x9FFF),    # hanzi – blok podstawowy (chiński i kanji)
    (0xF900, 0xFAFF),    # znaki zgodności
    (0xFF00, 0xFF60),    # znaki pełnej szerokości: ＡＢＣ１２３
    (0xFF61, 0xFF9F),    # katakana półszerokości: ｱｲｳ
    (0xAC00, 0xD7AF),    # hangul – sylaby koreańskie
)

#: Regex dopasowujący pojedynczy znak CJK — używany przez regułę wykluczającą.
CJK_CHAR_CLASS = "".join(f"\\u{low:04x}-\\u{high:04x}" for low, high in _CJK_RANGES)
CJK_PATTERN = f"[{CJK_CHAR_CLASS}]"
_CJK_RE = re.compile(CJK_PATTERN)


def contains_cjk(text: str) -> bool:
    """Czy tekst zawiera choć jeden znak japoński, chiński lub koreański.

    W plikach gier zdarzają się segmenty pozostawione w oryginale
    (``ポケモンに　きのみを\\nもたせて``). Nie ma ich po co tłumaczyć z polskiego
    projektu — lepiej oznaczyć je jako pominięte.
    """
    return bool(text) and bool(_CJK_RE.search(text))


def cjk_ratio(text: str) -> float:
    """Udział znaków CJK wśród znaków niebędących białymi (0.0–1.0)."""
    if not text:
        return 0.0
    visible = [c for c in text if not c.isspace()]
    if not visible:
        return 0.0
    return sum(1 for c in visible if _CJK_RE.match(c)) / len(visible)


def expand_ranges(pattern: str) -> List[str]:
    """Rozwija zapis zakresu ``TM01-TM66`` na listę pojedynczych haseł.

    Pozwala jedną regułą objąć cały ciąg numerowanych nazw — zamiast
    wpisywać sześćdziesiąt sześć osobnych wzorców. Obsługuje dowolny
    przedrostek i wiodące zera: ``HM01-HM28``, ``ITEM1-ITEM9``.
    Gdy zapis nie jest zakresem, zwraca ``[pattern]`` bez zmian.
    """
    match = re.fullmatch(
        r"\s*([^\d\s]*?)(\d+)\s*-\s*([^\d\s]*?)(\d+)\s*", pattern or "")
    if not match:
        return [pattern]
    prefix_a, start_txt, prefix_b, end_txt = match.groups()
    if prefix_a.lower() != prefix_b.lower():
        return [pattern]        # różne przedrostki – to nie jest zakres
    start, end = int(start_txt), int(end_txt)
    if start > end or end - start > 5000:
        return [pattern]        # odwrócony albo absurdalnie duży zakres
    width = len(start_txt) if start_txt.startswith("0") else 0
    return [f"{prefix_a}{str(n).zfill(width)}" for n in range(start, end + 1)]


BUILTIN_PRESETS: List[Tuple[str, ExclusionRule]] = [
    ("Teksty po japońsku / chińsku / koreańsku",
     ExclusionRule(CJK_PATTERN, "regex", True, False,
                   "segmenty zawierające znaki CJK – nietknięty oryginał")),
    ("Nagłówki plików  <<< FILE: … >>>",
     ExclusionRule("<<< FILE:*>>>", "wildcard", True, False,
                   "wiersze techniczne wskazujące plik źródłowy")),
    ("Znaczniki sekcji  <<< … >>>",
     ExclusionRule("<<<*>>>", "wildcard", False, False,
                   "dowolny wiersz w potrójnych nawiasach trójkątnych")),
    ("Dyrektywy asemblera  #org, #raw…",
     ExclusionRule(r"^\s*#\w+", "regex", False, False,
                   "wiersze zaczynające się od # (np. #org @8005A2)")),
    ("Sam znacznik lub zmienna  {STR_VAR_1}",
     ExclusionRule(r"^[\s\\ntpl]*(\{[A-Za-z0-9_]+\}[\s\\ntpl]*)+$", "regex", False, False,
                   "segment bez tekstu – wyłącznie zmienne i znaczniki")),
    ("Same liczby i symbole",
     ExclusionRule(r"^[\W\d_]+$", "regex", False, False,
                   "segment bez ani jednej litery")),
    ("Ścieżki plików  …/…​.inc",
     ExclusionRule(r"[\w/\\]+\.(inc|s|asm|txt|json)\b", "regex", False, False,
                   "wiersze zawierające ścieżkę do pliku")),
    ("Etykiety w nawiasach kwadratowych  [ETYKIETA]",
     ExclusionRule(r"^\s*\[[A-Za-z0-9_]+\]\s*$", "regex", False, False,
                   "segment będący samą etykietą")),
]


def default_rules() -> List[ExclusionRule]:
    """Zestaw startowy dla nowego projektu — wszystkie reguły wbudowane włączone."""
    return [ExclusionRule.from_dict(rule.to_dict()) for _name, rule in BUILTIN_PRESETS]


class ExclusionSet:
    """Zbiór reguł wykluczania – zapisywany w pliku projektu."""

    def __init__(self, rules: Optional[Sequence[ExclusionRule]] = None,
                 enabled: bool = True) -> None:
        self.rules: List[ExclusionRule] = list(rules) if rules is not None else []
        #: Główny wyłącznik – pozwala tymczasowo wyłączyć całe wykluczanie.
        self.enabled = enabled

    # ------------------------------------------------------- serializacja
    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "rules": [r.to_dict() for r in self.rules],
            "builtin_version": BUILTIN_VERSION,
        }

    @staticmethod
    def from_dict(data: Optional[dict]) -> "ExclusionSet":
        if not data:
            return ExclusionSet(default_rules())
        rules = [ExclusionRule.from_dict(r) for r in data.get("rules", [])]
        # Nowe reguły wbudowane (np. „teksty po japońsku / chińsku”) mają
        # działać także w starych projektach: tych, których nie ma w
        # zapisanej liście, dokładamy (domyślnie włączone — tak samo jak
        # przy nowym projekcie). Ręcznie zmienione/wpisane reguły zostają
        # nietknięte. Projekty zapisane bieżącą wersją (z „builtin_version”)
        # odczytujemy 1:1 — ich lista reguł jest już kompletna.
        if int(data.get("builtin_version", 0)) < BUILTIN_VERSION:
            have = {r.pattern for r in rules}
            for _name, builtin in BUILTIN_PRESETS:
                if builtin.pattern not in have:
                    rules.append(ExclusionRule.from_dict(builtin.to_dict()))
        return ExclusionSet(rules, bool(data.get("enabled", True)))

    # ------------------------------------------------------------ użycie
    @property
    def active_rules(self) -> List[ExclusionRule]:
        return [r for r in self.rules if r.enabled and r.pattern]

    def matching_rule(self, text: str, file_name: str = "") -> Optional[ExclusionRule]:
        """Pierwsza reguła obejmująca segment (albo None)."""
        if not self.enabled:
            return None
        for rule in self.active_rules:
            if rule.matches(text, file_name):
                return rule
        return None

    def is_excluded(self, text: str, file_name: str = "") -> bool:
        return self.matching_rule(text, file_name) is not None

    def apply(self, segments: Iterable, mark_ignored: bool = True) -> Tuple[int, int]:
        """Oznacza pasujące segmenty jako pominięte.

        Zwraca (nowo wykluczone, przywrócone). Decyzje użytkownika mają
        pierwszeństwo przed regułami i działają w OBIE strony:

        * ``manual_skip`` – segment pominięty ręcznie zostaje pominięty,
        * ``manual_keep`` – segment ręcznie przywrócony **nie zostanie ponownie
          wykluczony**, nawet jeśli pasuje do reguły.

        Bez tej drugiej flagi cofnięcie wykluczenia znikałoby przy każdym
        ponownym wczytaniu plików.
        """
        excluded = restored = 0
        for seg in segments:
            source = getattr(seg, "source", "") or ""
            name = getattr(seg, "file_name", "") or ""
            extra = getattr(seg, "extra", None)
            extra = extra if isinstance(extra, dict) else {}
            if extra.get("manual_keep"):
                continue            # użytkownik świadomie przywrócił ten segment

            should = self.is_excluded(source, name)
            was = bool(getattr(seg, "ignored", False))
            auto = bool(extra.get("auto_excluded"))

            if should and not was:
                if mark_ignored:
                    seg.ignored = True
                    if isinstance(getattr(seg, "extra", None), dict):
                        seg.extra["auto_excluded"] = True
                    excluded += 1
            elif not should and was and auto:
                # Reguła przestała pasować – przywracamy tylko to, co sami
                # wykluczyliśmy, nie ruszając ręcznych decyzji użytkownika.
                seg.ignored = False
                seg.extra.pop("auto_excluded", None)
                restored += 1
        return excluded, restored

    @staticmethod
    def clear_manual_decisions(segments: Iterable) -> int:
        """Kasuje ręczne wyjątki, przywracając pełne działanie reguł.

        Przydatne, gdy użytkownik „naklikał” wyjątków i chce zacząć od zera.
        """
        cleared = 0
        for seg in segments:
            extra = getattr(seg, "extra", None)
            if not isinstance(extra, dict):
                continue
            if extra.pop("manual_keep", None) is not None:
                cleared += 1
            if extra.pop("manual_skip", None) is not None:
                cleared += 1
        return cleared

    def preview(self, segments: Iterable, limit: int = 200) -> List[Tuple[int, str, str]]:
        """Lista trafień: (numer segmentu, tekst, opis reguły) – do podglądu."""
        out: List[Tuple[int, str, str]] = []
        for index, seg in enumerate(segments):
            rule = self.matching_rule(getattr(seg, "source", "") or "",
                                      getattr(seg, "file_name", "") or "")
            if rule is not None:
                out.append((index, getattr(seg, "source", "") or "", rule.describe()))
                if len(out) >= limit:
                    break
        return out

    def counts(self, segments: Iterable) -> Dict[str, int]:
        """Ile segmentów obejmuje każda reguła (do pokazania w tabeli)."""
        result: Dict[str, int] = {r.pattern: 0 for r in self.rules}
        if not self.enabled:
            return result
        active = self.active_rules
        for seg in segments:
            text = getattr(seg, "source", "") or ""
            name = getattr(seg, "file_name", "") or ""
            for rule in active:
                if rule.matches(text, name):
                    result[rule.pattern] = result.get(rule.pattern, 0) + 1
                    break
        return result
