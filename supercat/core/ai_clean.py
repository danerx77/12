"""Wydobywanie czystego tłumaczenia z „gadatliwej” odpowiedzi modelu AI.

Modele rozumujące (Gemini, Gemma, DeepSeek, Qwen…) często zwracają cały tok
rozumowania zamiast samego wyniku::

    * Role: Professional translator (English to Polish).
    * "Thank you for using" -> "Dziękujemy za korzystanie z"
    * Self-correction: ...
    Result: Dziękujemy za korzystanie z MYSTERY

Do segmentu ma trafić wyłącznie ostatnia linia. Ten moduł rozpoznaje typowe
wzorce takich odpowiedzi i wyciąga właściwe tłumaczenie.
"""
from __future__ import annotations

import re
from typing import List, Optional

#: Bloki „myślenia” wstawiane przez modele rozumujące.
_THINK_BLOCKS = [
    re.compile(r"<think>.*?</think>", re.S | re.I),
    re.compile(r"<thinking>.*?</thinking>", re.S | re.I),
    re.compile(r"<reasoning>.*?</reasoning>", re.S | re.I),
    re.compile(r"<scratchpad>.*?</scratchpad>", re.S | re.I),
    re.compile(r"◁think▷.*?◁/think▷", re.S),
]

#: Etykiety, po których model podaje ostateczny wynik.
_RESULT_LABELS = re.compile(
    r"^\s*(?:\*+\s*)?(?:final\s+)?"
    r"(?:result|translation|output|answer|final answer|final choice|final|"
    r"tłumaczenie|wynik|odpowiedź|rezultat)"
    r"\s*[:\-–]\s*",
    re.I,
)

#: Wiersze będące rozumowaniem, nie tłumaczeniem.
_REASONING_MARKERS = re.compile(
    r"^\s*(?:[*\-•]|\d+[.)])\s+|"
    r"^\s*(?:role|task|constraint|source text|input text|source language|"
    r"target language|context|option|options|analysis|note|notes|reasoning|"
    r"self-correction|wait|let's|let me|actually|however|looking at|given|"
    r"considering|checking|conclusion|explanation|hmm|okay|ok,)\b",
    re.I,
)

#: Zdania meta o samym tłumaczeniu (po polsku i angielsku).
_META_SENTENCE = re.compile(
    r"^\s*(?:here\s+is|here's|this\s+is|the\s+translation|i\s+(?:will|would|"
    r"can|think)|oto|poniżej|przetłumaczone|tłumaczenie\s+to)\b",
    re.I,
)


def _finalize(text: str) -> str:
    """Ostatnie porządki: cudzysłowy, warianty, powtórzenia."""
    out = _strip_wrapping_quotes(text)
    out = _drop_variants(out)
    out = _strip_wrapping_quotes(out)
    return _drop_immediate_repeat(out)


def _strip_wrapping_quotes(text: str) -> str:
    """Zdejmuje cudzysłowy obejmujące CAŁY tekst (nie te w środku)."""
    text = text.strip()
    pairs = [('"', '"'), ("'", "'"), ("„", "”"), ("«", "»"), ("“", "”"), ("‘", "’")]
    changed = True
    while changed and len(text) >= 2:
        changed = False
        for left, right in pairs:
            if text.startswith(left) and text.endswith(right):
                inner = text[len(left):-len(right)]
                # nie obcinaj, jeśli cudzysłów zamyka się w środku (to część tekstu)
                if right not in inner:
                    text = inner.strip()
                    changed = True
                    break
    return text


def _strip_code_fence(text: str) -> str:
    """Usuwa obudowanie ```…``` wokół całej odpowiedzi."""
    match = re.match(r"^\s*```[a-zA-Z0-9_+-]*\s*\n(.*?)\n?\s*```\s*$", text, re.S)
    return match.group(1).strip() if match else text


def _looks_like_reasoning(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if _REASONING_MARKERS.search(stripped):
        return True
    if _META_SENTENCE.search(stripped):
        return True
    # strzałki typu  "x" -> "y"  to zapis rozumowania
    if "->" in stripped or "→" in stripped or "-&gt;" in stripped:
        return True
    return False


#: Warianty podawane przez model: "Wersja A" or "Wersja B" / „A” lub „B”.
_VARIANT_SPLIT = re.compile(r'^\s*"([^"]{3,})"\s+(?:or|lub|albo)\s+"([^"]{3,})"\s*$', re.I)


def _drop_variants(text: str) -> str:
    """Z dwóch propozycji rozdzielonych „or”/„lub” zostawia pierwszą."""
    match = _VARIANT_SPLIT.match(text.strip())
    return match.group(1).strip() if match else text


def _drop_immediate_repeat(text: str) -> str:
    """Usuwa natychmiastowe podwojenie tej samej treści.

    Model bywa, że zwraca „Zdanie.Zdanie.” albo „Zdanie.\nZdanie.” –
    bez tego tekst trafiał do segmentu podwojony.
    """
    stripped = text.strip()
    if not stripped:
        return text
    half = len(stripped) // 2
    # dokładne podwojenie (ewentualnie z separatorem w środku)
    for sep in ("", "\n", " "):
        if len(stripped) % 2 == len(sep) % 2:
            first = stripped[:half]
            rest = stripped[half:]
            if sep and rest.startswith(sep):
                rest = rest[len(sep):]
            if first and first == rest:
                return first.strip()
    # powtórzone linie – także gdy jedna z nich jest w cudzysłowie
    lines = [l.strip() for l in stripped.splitlines() if l.strip()]
    if len(lines) == 2:
        bare = [_strip_wrapping_quotes(l) for l in lines]
        if bare[0] == bare[1]:
            return bare[0]
    return stripped


def clean_ai_translation(raw: str, source_text: str = "") -> str:
    """Zwraca samo tłumaczenie, odrzucając rozumowanie modelu.

    `source_text` (opcjonalny) pomaga odrzucić linie, w których model po prostu
    powtórzył tekst źródłowy.
    """
    if not raw:
        return ""

    text = raw
    for pattern in _THINK_BLOCKS:
        text = pattern.sub(" ", text)
    text = _strip_code_fence(text.strip())

    # 1) Najpewniejszy sygnał: jawna etykieta wyniku – bierzemy OSTATNIĄ.
    labelled: List[str] = []
    for line in text.splitlines():
        if _RESULT_LABELS.match(line):
            value = _RESULT_LABELS.sub("", line).strip()
            if value:
                labelled.append(value)
    if labelled:
        candidate = _finalize(labelled[-1])
        if candidate:
            return candidate

    lines = [l.rstrip() for l in text.splitlines()]
    non_empty = [l for l in lines if l.strip()]
    if not non_empty:
        return ""

    # 2) Odpowiedź jednolinijkowa – zwykle po prostu tłumaczenie.
    if len(non_empty) == 1:
        return _finalize(non_empty[0])

    # 3) Odfiltruj linie rozumowania; weź ostatni sensowny wiersz.
    source_norm = (source_text or "").strip().lower()
    plain = [
        l.strip() for l in non_empty
        if not _looks_like_reasoning(l) and l.strip().lower() != source_norm
    ]
    if plain:
        return _finalize("\n".join(plain) if len(plain) > 1 else plain[-1])

    # 4) Same rozumowanie – spróbuj wyłuskać ostatni cytat z linii ze strzałką.
    for line in reversed(non_empty):
        quotes = re.findall(r'"([^"]{2,})"', line)
        if quotes:
            return _finalize(quotes[-1])

    return _finalize(non_empty[-1])


def build_translation_prompt(source_lang: str, target_lang: str,
                             instructions: str = "", glossary: Optional[List[tuple]] = None,
                             context: str = "", grammar_rules: Optional[bool] = None) -> str:
    """Buduje polecenie systemowe dla modelu AI.

    Nacisk położony jest na to, by model **nie** dopisywał rozumowania —
    to najczęstsza przyczyna zaśmiecania tłumaczeń.
    """
    parts = [
        f"Jesteś profesjonalnym tłumaczem {source_lang} → {target_lang}, "
        f"native speakerem języka docelowego i redaktorem dbającym o poprawną odmianę.",
        "Przetłumacz WYŁĄCZNIE tekst podany przez użytkownika.",
        "",
        "ZASADY ODPOWIEDZI (bezwzględne):",
        "1. Zwróć tylko i wyłącznie samo tłumaczenie.",
        "2. Nie dopisuj wyjaśnień, analiz, wariantów ani komentarzy.",
        "3. Nie pokazuj toku rozumowania. Żadnych list, punktów ani etykiet "
        "typu „Result:”, „Translation:”, „Option 1”.",
        "4. Nie otaczaj odpowiedzi cudzysłowami ani znacznikami kodu.",
        "5. Zachowaj WSZYSTKIE symbole zastępcze @#0#@, @#1#@, @#2#@ … dokładnie "
        "w tej samej postaci, liczbie i kolejności, w jakiej występują w oryginale. "
        "Nie usuwaj ich, nie tłumacz, nie dodawaj nowych, nie wstawiaj wokół nich spacji. "
        "To znaczniki końca wiersza i zmienne programu — ich brak psuje plik.",
        "",
        "6. NAJWAŻNIEJSZE — symbole zastępcze to TYLKO przełamania wiersza na ekranie, "
        "a NIE granice zdań. Zdanie bardzo często biegnie DALEJ przez symbol.",
        "   Czytaj tekst tak, jakby symboli nie było, przetłumacz go jako całość, "
        "a dopiero potem rozstaw symbole w tłumaczeniu w naturalnych miejscach.",
        "   Przykład: „the STAMP CARD@#0#@System.” to jedno wyrażenie "
        "„the STAMP CARD System” (nazwa systemu) przełamane w środku — "
        "przetłumacz je jako całość, np. „SYSTEM KART@#0#@ZBIERANIA PIECZĄTEK”, "
        "a NIE jako dwa osobne zdania „KARTA” i „System”.",
        "   Nigdy nie tłumacz fragmentu między symbolami jako samodzielnego zdania.",
        "",
        "7. Zachowaj wielkość liter nazw własnych zapisanych wersalikami.",
    ]

    if grammar_rules is None:
        try:
            from .settings import SettingsManager

            grammar_rules = SettingsManager.instance().get_bool("mt.ai.grammar.rules", True)
        except Exception:
            grammar_rules = True

    if grammar_rules:
        parts += [
        "",
        "JAKOŚĆ JĘZYKA DOCELOWEGO (równie ważne jak wierność):",
        "7a. Tłumaczenie ma brzmieć NATURALNIE — tak, jakby od razu napisano je "
        "w języku docelowym. Nie kalkuj składni oryginału.",
        "7b. Dopilnuj poprawnej ODMIANY: przypadków, liczby, rodzaju i osoby. "
        "Rzeczownik po liczebniku odmień prawidłowo "
        "(np. „5 apples” → „pięć jabłek”, nie „pięć jabłko”).",
        "7c. Uzgodnij przymiotniki i imiesłowy z rzeczownikiem "
        "co do rodzaju, liczby i przypadku.",
        "7d. Zachowaj poprawny szyk zdania oraz interpunkcję języka docelowego "
        "(m.in. przecinki przed „że”, „który”, „aby”; cudzysłowy „ ”).",
        "7e. Utrzymaj JEDNOLITĄ formę zwracania się do odbiorcy w całym tekście "
        "(konsekwentnie ta sama osoba i liczba).",
        "7f. Zmienne w nawiasach klamrowych (np. {PLAYER}, {STR_VAR_1}) to wstawiane "
        "w grze wyrazy — buduj zdanie tak, aby po podstawieniu było poprawne gramatycznie.",
        "7g. Nazwy własne i terminy zapisane WERSALIKAMI odmieniaj wyłącznie przez "
        "wyrazy im towarzyszące, samej nazwy nie zmieniaj.",
        ]

    parts += [
        "8. Podaj DOKŁADNIE JEDNĄ wersję tłumaczenia. Nie powtarzaj go dwa razy, "
        "nie podawaj wariantów rozdzielonych „or”/„lub”, nie proponuj alternatyw.",
        "9. Przetłumacz cały tekst, łącznie z fragmentami po symbolach zastępczych.",
        "10. Jeśli tekstu nie da się przetłumaczyć, zwróć go bez zmian.",
    ]
    if glossary:
        parts.append("")
        parts.append("Obowiązkowa terminologia (używaj dokładnie tych odpowiedników):")
        for src, tgt in glossary[:40]:
            parts.append(f"- {src} → {tgt}")
    if context:
        parts.append("")
        parts.append(f"Kontekst dokumentu: {context}")
    if instructions:
        parts.append("")
        parts.append(f"Dodatkowe wytyczne: {instructions}")
    return "\n".join(parts)
