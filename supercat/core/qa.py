"""Kontrola jakości QA + statystyki.

Odpowiednik gui/dialogs/QADialog.java oraz services/StatisticsService.java.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from .fileparser import Segment
from .settings import SettingsManager
from .langcheck import MIN_DICTIONARY_FOR_SPELLCHECK
from .tags import count_tags, extract_tags
from .textutil import describe_edges, split_edges

SEVERITY_ERROR = "błąd"
SEVERITY_WARNING = "ostrzeżenie"
SEVERITY_INFO = "info"


@dataclass
class QAIssue:
    segment_index: int
    category: str
    severity: str
    message: str
    detail: str = ""


def run_qa(segments: List[Segment], glossary=None, dictionary=None) -> List[QAIssue]:
    """Uruchamia wszystkie włączone kontrole QA dla listy segmentów."""
    settings = SettingsManager.instance()
    issues: List[QAIssue] = []

    check_numbers = settings.get_bool("qa.check.numbers", True)
    check_tags = settings.get_bool("qa.check.tags", True)
    check_length = settings.get_bool("qa.check.length", True)
    check_punct = settings.get_bool("qa.check.punctuation", True)
    check_caps = settings.get_bool("qa.check.capitalization", True)
    check_empty = settings.get_bool("qa.check.empty", True)
    check_consistency = settings.get_bool("qa.check.consistency", True)
    check_whitespace = settings.get_bool("qa.check.whitespace", True)
    check_language = settings.get_bool("qa.check.language", True)

    for idx, seg in enumerate(segments):
        if seg.ignored:
            continue
        source, target = seg.source or "", seg.target or ""

        if check_empty and not target.strip():
            issues.append(QAIssue(idx, "Puste tłumaczenie", SEVERITY_ERROR,
                                  "Segment nie został przetłumaczony", source[:80]))
            continue

        if check_numbers:
            s_nums, t_nums = _numbers(source), _numbers(target)
            if sorted(s_nums) != sorted(t_nums):
                issues.append(QAIssue(idx, "Liczby", SEVERITY_WARNING,
                                      "Różne wartości liczbowe",
                                      f"źródło: {s_nums or '—'} → cel: {t_nums or '—'}"))

        if check_tags:
            s_tags = count_tags(source)
            t_tags = count_tags(target)
            if s_tags != t_tags:
                issues.append(QAIssue(idx, "Tagi", SEVERITY_ERROR,
                                      "Różna liczba tagów",
                                      f"źródło: {s_tags} → cel: {t_tags}"))
            else:
                s_set = sorted(t.text for t in extract_tags(source))
                t_set = sorted(t.text for t in extract_tags(target))
                if s_set != t_set:
                    issues.append(QAIssue(idx, "Tagi", SEVERITY_WARNING,
                                          "Inna treść tagów",
                                          f"{s_set} → {t_set}"))

        # bardzo krótkie segmenty (tytuły, etykiety) naturalnie zmieniają długość –
        # kontrola proporcji ma sens dopiero od ok. 20 znaków
        if check_length and len(source) >= 20 and target:
            ratio = len(target) / len(source)
            if ratio < 0.5:
                issues.append(QAIssue(idx, "Długość", SEVERITY_WARNING,
                                      "Tłumaczenie bardzo krótkie",
                                      f"{len(source)} → {len(target)} znaków ({ratio * 100:.0f}%)"))
            elif ratio > 2.0:
                issues.append(QAIssue(idx, "Długość", SEVERITY_WARNING,
                                      "Tłumaczenie bardzo długie",
                                      f"{len(source)} → {len(target)} znaków ({ratio * 100:.0f}%)"))

        if check_punct and source.strip() and target.strip():
            s_last, t_last = source.strip()[-1], target.strip()[-1]
            if _is_punct(s_last) and not _is_punct(t_last):
                issues.append(QAIssue(idx, "Interpunkcja", SEVERITY_WARNING,
                                      "Brak znaku interpunkcyjnego na końcu",
                                      f"źródło kończy się na „{s_last}”"))
            elif not _is_punct(s_last) and _is_punct(t_last):
                issues.append(QAIssue(idx, "Interpunkcja", SEVERITY_INFO,
                                      "Nadmiarowy znak interpunkcyjny na końcu",
                                      f"cel kończy się na „{t_last}”"))
            if source.count('"') != target.count('"'):
                issues.append(QAIssue(idx, "Interpunkcja", SEVERITY_INFO,
                                      "Różna liczba cudzysłowów", ""))

        if check_caps and source.strip() and target.strip():
            s_first, t_first = source.strip()[0], target.strip()[0]
            if s_first.isalpha() and t_first.isalpha():
                if s_first.isupper() and t_first.islower():
                    issues.append(QAIssue(idx, "Wielkość liter", SEVERITY_INFO,
                                          "Źródło z wielkiej litery, tłumaczenie z małej", ""))

        if source.strip() and source.strip() == target.strip():
            issues.append(QAIssue(idx, "Nieprzetłumaczone", SEVERITY_WARNING,
                                  "Tłumaczenie identyczne ze źródłem", source[:80]))

        # Wcięcie na początku/końcu wiersza jest w plikach gier zamierzone –
        # sprawdzamy tylko wnętrze tekstu.
        if re.search(r"\S[ \t]{2,}\S", target):
            issues.append(QAIssue(idx, "Białe znaki", SEVERITY_INFO, "Podwójne spacje w tłumaczeniu", ""))

        if check_whitespace and target.strip():
            s_lead, _s_core, s_trail = split_edges(source)
            t_lead, _t_core, t_trail = split_edges(target)
            if s_lead != t_lead or s_trail != t_trail:
                issues.append(QAIssue(
                    idx, "Białe znaki", SEVERITY_WARNING,
                    "Inne spacje na brzegach niż w źródle",
                    f"źródło: {describe_edges(source) or 'brak'} → "
                    f"tłumaczenie: {describe_edges(target) or 'brak'}"))

        if glossary is not None and getattr(glossary, "entries", None):
            reported: set[tuple[str, str]] = set()
            for term in glossary.find_terms(source):
                key = (term.source.lower(), term.target.lower())
                if key in reported or not term.target:
                    continue
                reported.add(key)
                if term.target.lower() not in target.lower():
                    issues.append(QAIssue(idx, "Glosariusz", SEVERITY_WARNING,
                                          f"Nie użyto terminu „{term.target}”",
                                          f"{term.source} → {term.target}"))

        if (dictionary is not None and getattr(dictionary, "is_initialized", False)
                and getattr(dictionary, "size", 0) >= MIN_DICTIONARY_FOR_SPELLCHECK):
            unknown = dictionary.check_text(target)
            if unknown:
                issues.append(QAIssue(idx, "Pisownia", SEVERITY_INFO,
                                      "Słowa spoza słownika", ", ".join(unknown[:8])))

        # Kontrola poprawności języka – TYLKO tłumaczenie, nigdy źródło.
        if check_language and target.strip():
            from .langcheck import check_offline, options_from_settings

            for lang_issue in check_offline(target, dictionary, options_from_settings())[:10]:
                severity = {
                    "błąd": SEVERITY_ERROR,
                    "ostrzeżenie": SEVERITY_WARNING,
                }.get(lang_issue.severity, SEVERITY_INFO)
                detail = lang_issue.fragment
                if lang_issue.suggestions:
                    detail += "  →  " + ", ".join(lang_issue.suggestions[:2])
                issues.append(QAIssue(idx, f"Język: {lang_issue.category}", severity,
                                      lang_issue.message, detail.strip()))

    if check_consistency:
        issues.extend(_consistency_check(segments))

    issues.sort(key=lambda i: (i.segment_index, i.category))
    return issues


def _consistency_check(segments: List[Segment]) -> List[QAIssue]:
    """Ten sam tekst źródłowy przetłumaczony na różne sposoby (i odwrotnie)."""
    issues: List[QAIssue] = []
    by_source: Dict[str, Dict[str, List[int]]] = {}
    by_target: Dict[str, Dict[str, List[int]]] = {}

    for idx, seg in enumerate(segments):
        if seg.ignored or not seg.is_translated:
            continue
        s_key, t_key = seg.source.strip().lower(), seg.target.strip().lower()
        by_source.setdefault(s_key, {}).setdefault(t_key, []).append(idx)
        by_target.setdefault(t_key, {}).setdefault(s_key, []).append(idx)

    for source, variants in by_source.items():
        if len(variants) > 1:
            first_idx = min(min(v) for v in variants.values())
            issues.append(QAIssue(first_idx, "Spójność", SEVERITY_WARNING,
                                  "Ten sam tekst źródłowy ma różne tłumaczenia",
                                  " | ".join(list(variants.keys())[:3])))
    for target, variants in by_target.items():
        if len(variants) > 1:
            first_idx = min(min(v) for v in variants.values())
            issues.append(QAIssue(first_idx, "Spójność", SEVERITY_INFO,
                                  "To samo tłumaczenie dla różnych źródeł",
                                  " | ".join(list(variants.keys())[:3])))
    return issues


def _numbers(text: str) -> List[str]:
    return re.findall(r"\d+(?:[.,]\d+)?", text or "")


def _is_punct(ch: str) -> bool:
    return ch in ".,;:!?…»«\"')]}"


# ------------------------------------------------------------------ statystyki
def word_count(text: str) -> int:
    return len(re.findall(r"[\w'\-]+", text or "", flags=re.UNICODE))


#: Statusy domykające segment – zgodne z edytorem (patrz ui/editor_tab.py).
DONE_STATUSES = ("translated", "approved")


def is_done(seg) -> bool:
    """Segment gotowy: ma tłumaczenie albo oznaczenie „przetłumaczony”/„zatwierdzony”."""
    if getattr(seg, "status", "") in DONE_STATUSES:
        return True
    return bool((getattr(seg, "target", "") or "").strip())


def chars_no_spaces(text: str) -> int:
    """Znaki bez spacji – miara używana w rozliczeniach tłumaczeń."""
    return sum(1 for ch in (text or "") if not ch.isspace())


def _codes_in(text: str) -> int:
    """Liczba znaczników sterujących (\\n, \\p, <<KON>>, {ZMIENNA})."""
    return len(_CODE_COUNT_RE.findall(text or ""))


#: Znaczniki plików gier – liczone osobno, bo nie są tekstem do tłumaczenia.
_CODE_COUNT_RE = re.compile(r"\\[a-zA-Z]|<<[^<>]{1,24}>>|\{[A-Za-z0-9_]{1,32}\}")

#: Umowna strona rozliczeniowa (znaki ze spacjami).
STANDARD_PAGE_CHARS = 1800


def project_statistics(segments: List[Segment], tm_size: int = 0) -> Dict[str, object]:
    total = len(segments)
    translated = sum(1 for s in segments if is_done(s))
    ignored = sum(1 for s in segments if s.ignored)
    approved = sum(1 for s in segments if s.status == "approved")
    draft = sum(1 for s in segments if s.status == "draft" and s.is_translated)

    source_words = sum(word_count(s.source) for s in segments)
    target_words = sum(word_count(s.target) for s in segments)
    source_chars = sum(len(s.source or "") for s in segments)
    target_chars = sum(len(s.target or "") for s in segments)
    source_chars_ns = sum(chars_no_spaces(s.source) for s in segments)
    target_chars_ns = sum(chars_no_spaces(s.target) for s in segments)

    pending = [s for s in segments if not is_done(s) and not s.ignored]
    remaining_words = sum(word_count(s.source) for s in pending)
    remaining_chars = sum(len(s.source or "") for s in pending)

    files = sorted({s.file_name for s in segments if s.file_name})
    unique_sources = {(s.source or "").strip() for s in segments if (s.source or "").strip()}
    repeated = len([s for s in segments if (s.source or "").strip()]) - len(unique_sources)
    codes = sum(_codes_in(s.source) for s in segments)
    lengths = [word_count(s.source) for s in segments if (s.source or "").strip()]

    return {
        # --- postęp ---
        "Segmenty (razem)": total,
        "Segmenty przetłumaczone": translated,
        "Segmenty pozostałe": total - translated,
        "Segmenty zatwierdzone": approved,
        "Segmenty robocze": draft,
        "Segmenty pominięte": ignored,
        "Postęp (%)": round(translated * 100 / total, 1) if total else 0.0,
        # --- słowa ---
        "Słowa (źródło)": source_words,
        "Słowa (tłumaczenie)": target_words,
        "Słowa do przetłumaczenia": remaining_words,
        # --- znaki ---
        "Znaki ze spacjami (źródło)": source_chars,
        "Znaki bez spacji (źródło)": source_chars_ns,
        "Znaki ze spacjami (tłumaczenie)": target_chars,
        "Znaki bez spacji (tłumaczenie)": target_chars_ns,
        "Znaki do przetłumaczenia": remaining_chars,
        # --- rozliczenie ---
        "Strony rozliczeniowe (1800 zn.)": round(source_chars / STANDARD_PAGE_CHARS, 2),
        "Średnia długość segmentu (słowa)": round(sum(lengths) / len(lengths), 1) if lengths else 0.0,
        "Najdłuższy segment (słowa)": max(lengths) if lengths else 0,
        # --- pozostałe ---
        "Segmenty powtórzone": repeated,
        "Znaczniki w źródle": codes,
        "Wpisy w TM": tm_size,
        "Pliki w projekcie": len(files),
    }


def file_statistics(segments: List[Segment]) -> List[Dict[str, object]]:
    """Statystyki w rozbiciu na pliki – do tabeli w zakładce QA."""
    by_file: Dict[str, List[Segment]] = {}
    for seg in segments:
        by_file.setdefault(seg.file_name or "(bez pliku)", []).append(seg)

    rows: List[Dict[str, object]] = []
    for name, items in sorted(by_file.items()):
        done = sum(1 for s in items if is_done(s))
        rows.append({
            "Plik": name,
            "Segmenty": len(items),
            "Przetłumaczone": done,
            "Postęp (%)": round(done * 100 / len(items), 1) if items else 0.0,
            "Słowa (źródło)": sum(word_count(s.source) for s in items),
            "Znaki ze spacjami": sum(len(s.source or "") for s in items),
            "Znaki bez spacji": sum(chars_no_spaces(s.source) for s in items),
        })
    return rows


def segment_statistics(source: str, target: str) -> Dict[str, object]:
    src_words, tgt_words = word_count(source), word_count(target)
    src_chars, tgt_chars = len(source or ""), len(target or "")
    return {
        "Słowa (źródło)": src_words,
        "Słowa (tłumaczenie)": tgt_words,
        "Znaki ze spacjami (źródło)": src_chars,
        "Znaki bez spacji (źródło)": chars_no_spaces(source),
        "Znaki ze spacjami (tłumaczenie)": tgt_chars,
        "Znaki bez spacji (tłumaczenie)": chars_no_spaces(target),
        "Zdania (źródło)": len([p for p in re.split(r"[.!?…]+", source or "") if p.strip()]),
        "Stosunek długości (%)": round(tgt_chars * 100 / src_chars, 1) if src_chars else 0.0,
        "Tagi (źródło)": count_tags(source),
        "Tagi (tłumaczenie)": count_tags(target),
        "Znaczniki (źródło)": _codes_in(source),
        "Znaczniki (tłumaczenie)": _codes_in(target),
    }


def qa_report_text(issues: List[QAIssue], segments: List[Segment]) -> str:
    lines = ["=== RAPORT QA – SuperCAT ===", ""]
    lines.append(f"Liczba problemów: {len(issues)}")
    lines.append("")
    for issue in issues:
        seg = segments[issue.segment_index] if 0 <= issue.segment_index < len(segments) else None
        lines.append(f"[{issue.severity.upper()}] Segment {issue.segment_index + 1} – {issue.category}: {issue.message}")
        if issue.detail:
            lines.append(f"    {issue.detail}")
        if seg:
            lines.append(f"    Źródło: {seg.source[:120]}")
            lines.append(f"    Cel:    {seg.target[:120]}")
        lines.append("")
    return "\n".join(lines)
