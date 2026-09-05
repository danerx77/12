"""Ochrona i adaptacja tagów (odpowiednik services/TagProtectionService.java)."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .textutil import split_edges


class TagType(str, Enum):
    VARIABLE = "VARIABLE"
    NEWLINE = "NEWLINE"
    END = "END"
    HTML = "HTML"
    BRACKET = "BRACKET"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class TagInfo:
    text: str
    start: int
    type: TagType


TAG_PATTERNS = [
    re.compile(r"\{([A-Za-z_0-9]+)\}"),
    re.compile(r"\\[pPnNlL]"),
    re.compile(r"<<KON>>"),
    re.compile(r"<[^>]+>"),
    re.compile(r"\[[^\]]+\]"),
]


def _tag_type(tag: str) -> TagType:
    if tag.startswith("{") and tag.endswith("}"):
        return TagType.VARIABLE
    if tag.startswith("\\") and len(tag) == 2:
        return TagType.NEWLINE
    if tag == "<<KON>>":
        return TagType.END
    if tag.startswith("<") and tag.endswith(">"):
        return TagType.HTML
    if tag.startswith("[") and tag.endswith("]"):
        return TagType.BRACKET
    return TagType.UNKNOWN


def extract_tags(text: str | None) -> List[TagInfo]:
    """Zwraca listę tagów w kolejności wystąpienia."""
    tags: List[TagInfo] = []
    if not text:
        return tags
    for pattern in TAG_PATTERNS:
        for match in pattern.finditer(text):
            tags.append(TagInfo(match.group(), match.start(), _tag_type(match.group())))
    tags.sort(key=lambda t: t.start)
    return tags


def count_tags(text: str | None) -> int:
    return len(extract_tags(text))


def remove_tags(text: str | None) -> str:
    if not text:
        return ""
    result = text
    for pattern in TAG_PATTERNS:
        result = pattern.sub("", result)
    return result.strip()


def _group_tags(tags: List[TagInfo]) -> List[List[TagInfo]]:
    """Grupuje tagi sąsiadujące ze sobą (bez odstępu)."""
    groups: List[List[TagInfo]] = []
    if not tags:
        return groups
    current = [tags[0]]
    for prev, curr in zip(tags, tags[1:]):
        if prev.start + len(prev.text) == curr.start:
            current.append(curr)
        else:
            groups.append(current)
            current = [curr]
    groups.append(current)
    return groups


def adapt_translation(source_text: str | None, tm_translation: str | None) -> str:
    """Dopasowuje tagi z bieżącego segmentu źródłowego do tłumaczenia z TM.

    Tagi w tłumaczeniu z pamięci są zastępowane tagami z aktualnego źródła
    (typ po typie, grupa po grupie), dzięki czemu podpowiedź TM pasuje do
    aktualnego segmentu nawet gdy numery zmiennych są inne.
    """
    if source_text is None or tm_translation is None:
        return tm_translation or ""

    source_tags = extract_tags(source_text)
    tm_tags = extract_tags(tm_translation)
    if not source_tags and not tm_tags:
        return tm_translation

    replacements: List[tuple[int, int, str]] = []
    for tag_type in TagType:
        s_groups = _group_tags([t for t in source_tags if t.type == tag_type])
        t_groups = _group_tags([t for t in tm_tags if t.type == tag_type])
        for idx, t_group in enumerate(t_groups):
            start = t_group[0].start
            end = t_group[-1].start + len(t_group[-1].text)
            replacement = "".join(t.text for t in s_groups[idx]) if idx < len(s_groups) else ""
            replacements.append((start, end, replacement))

    # zamiany od końca, aby nie przesuwać indeksów
    replacements.sort(key=lambda r: r[0], reverse=True)
    result = tm_translation
    for start, end, replacement in replacements:
        result = result[:start] + replacement + result[end:]
    result = result.strip()
    return trim_break_spaces(source_text, result)


def normalize_tags_for_comparison(text: str | None) -> str:
    """Normalizuje tagi do jednego znaku – dla porównań fuzzy."""
    if not text:
        return ""
    result = text
    result = re.sub(r"\{([A-Za-z_0-9]+)\}", "@", result)
    result = re.sub(r"\\[pPnNlL]", "~", result)
    result = result.replace("<<KON>>", "^")
    result = re.sub(r"<[^>]+>", "<", result)
    result = re.sub(r"\[[^\]]+\]", "[", result)
    return result


# ---------------------------------------------------------------------------
# Dopasowanie znaczników (\\n, \\l, \\p) do oryginału
# ---------------------------------------------------------------------------

#: Kod, który przełamuje wiersz w plikach gier: \\n (spacja w grze), \\l (bez),
#: \\p (nowy akapit). Wielkość liter nie ma znaczenia.
#: Domyślne kody przełamania wiersza i akapitu — DO WYBORU w ustawieniach
#: (``tm.adapt.line.codes`` / ``tm.adapt.para.codes``). Każda gra może używać
#: innych znaczników (np. ``\\N``, ``\\L``) — wystarczy je podać.
DEFAULT_LINE_BREAKS = ("\\n", "\\l")
DEFAULT_PARA_BREAKS = ("\\p",)

#: Znak, po którym można bezpiecznie przełamać wiersz (także pełnej
#: szerokości spacja CJK).
_BREAKABLE_AFTER = (" ", "\u3000")


def parse_break_codes(raw: str | None, default: Tuple[str, ...]) -> Tuple[str, ...]:
    """Wczytuje listę kodów z pola ustawień (znaczniki rozdzielone spacjami).

    Puste pole → domyślne kody. Każde pole jest literalnym ciągiem znaków
    (np. ``\n`` to backslash + litera, dokładnie tak jak w pliku gry).
    """
    if raw is None or not str(raw).strip():
        return tuple(default)
    codes = tuple(c for c in str(raw).split() if c)
    return codes if codes else tuple(default)


_BREAK_CACHE: Dict[Tuple[Tuple[str, ...], Tuple[str, ...]],
                   Tuple["re.Pattern", "set"]] = {}


#: Rodziny znaków, które w plikach gier wyglądają jak kody:
#: escape backslash + litery (\\n, \\N, \\nl…), zmienne {NAZWA}
#: i tagi <<NAZWA>>.
_ESCAPE_CODE_RE = re.compile(r"\\[A-Za-z]")
_VAR_CODE_RE = re.compile(r"\{[A-Za-z0-9_]+\}")
_TAG_CODE_RE = re.compile(r"<<[A-Za-z0-9_ ]+>>")


def ensure_line_widths(source: str | None, target: str | None,
                       line_breaks: Sequence[str] | None = None,
                       para_breaks: Sequence[str] | None = None) -> str:
    """Dokleja kody wiersza, gdy tłumaczenie jest dłuższe niż oryginał.

    Dotyczy segmentów, w których ORYGINAL nie ma kodów (jedna linia), a
    tłumaczenie wyrosło ponad najdłuższą linię oryginału — wtedy łamiemy
    przy spacji tak, by każda linia mieściła się w tej szerokości (w grze
    za długi wiersz nie wyjdzie w całości). Tłumaczenia z kodami albo krótkie
    zostają nietknięte.
    """
    if not source or not target:
        return target or ""
    src_paras = split_code_structure(source, line_breaks, para_breaks)
    if any(len(par) > 1 for par in src_paras):
        return target              # oryginał ma kody — adapt_codes się tym zajmuje
    allowed = max((len(line) for line, _c in src_paras[0]), default=len(source))
    if not allowed:
        return target
    tgt_paras = split_code_structure(target, line_breaks, para_breaks)
    if any(len(par) > 1 for par in tgt_paras):
        return target              # tłumaczenie już ma kody — nie ruszamy
    lead, core, trail = split_edges(target)
    if allowed < 12 or len(core) <= allowed + 2:
        return target              # za krótko / mieści się (z zapasem 2 znaki)
    out: List[str] = []
    cur = ""
    for word in core.split(" "):
        candidate = f"{cur} {word}" if cur else word
        if not cur or len(candidate) <= allowed:
            cur = candidate
        else:
            out.append(cur)
            cur = word
    if cur:
        out.append(cur)
    code = line_breaks[0] if line_breaks else DEFAULT_LINE_BREAKS[0]
    return lead + code.join(out) + trail


def detect_codes(text: str | None) -> Dict[str, int]:
    """Rozpoznaje kody w tekście i zwraca ``{kod: ile razy}``.

    Działa na DOWOLNYM tekście — bez konfiguracyjnej listy: program sam
    widzi, że ``\\N`` czy ``{VAR_1}`` to kod, bo tak wygląda (backslash
    + litery / klamry / podwójne nawiązy kwadratowe). Używane np. w
    przycisku „Wymień kody z plików” i w automatycznym dopasowaniu.
    """
    if not text:
        return {}
    found: Dict[str, int] = {}
    for rx in (_ESCAPE_CODE_RE, _VAR_CODE_RE, _TAG_CODE_RE):
        for match in rx.finditer(text):
            code = match.group()
            found[code] = found.get(code, 0) + 1
    return found


def parse_code_list(raw: str | None) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """Rozbija wklejoną listę kodów na (escape, inline).

    Lista to kody rozdzielone spacjami, np.
    ``\\n \\l \\p {VAR_1} <<KON>>``. Escape zaczynają się od backslasha;
    reszta (zmienne, tagi) to kody inline.
    """
    if not raw or not str(raw).strip():
        return (), ()
    parts = [c for c in str(raw).split() if c]
    esc = tuple(c for c in parts if c.startswith("\\"))
    inline = tuple(c for c in parts if c not in esc)
    return esc, inline


def effective_break_codes(
    source: str,
    line_codes: tuple[str, ...],
    para_codes: tuple[str, ...],
    extra_codes: tuple[str, ...] = (),
    auto_detect: bool = True,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Dopasowanie kodów: ustawienia + wklejona lista + auto-detekcja z tekstu."""
    line = tuple(dict.fromkeys(line_codes or ()))
    para = tuple(dict.fromkeys(para_codes or ()))
    if extra_codes:
        for c in extra_codes:
            if not isinstance(c, str) or not c or c in line or c in para:
                continue
            if c.lower().startswith("\\p"):
                para = para + (c,)
            else:
                line = line + (c,)
        line = tuple(dict.fromkeys(line))
        para = tuple(dict.fromkeys(para))
    if auto_detect:
        line_set = set(line)
        para_set = set(para)
        for c in detect_codes(source):
            if c in para_set or c in line_set:
                continue
            if c.lower().startswith("\\p"):
                para = para + (c,)
                para_set.add(c)
            else:
                line = line + (c,)
                line_set.add(c)
    return line, para
def _break_tables(line_breaks: Sequence[str] | None = None,
                  para_breaks: Sequence[str] | None = None) -> Tuple["re.Pattern", set]:
    """Skompilowany wzorzec kodów przełamania + zbiór kodów akapitowych."""
    line = tuple(line_breaks) if line_breaks else DEFAULT_LINE_BREAKS
    para = tuple(para_breaks) if para_breaks else DEFAULT_PARA_BREAKS
    key = (line, para)
    hit = _BREAK_CACHE.get(key)
    if hit is not None:
        return hit
    all_codes = sorted({c.lower() for c in line} | {c.lower() for c in para},
                       key=len, reverse=True)
    if not all_codes:
        all_codes = list(c.lower() for c in DEFAULT_LINE_BREAKS + DEFAULT_PARA_BREAKS)
    hit = (re.compile("|".join(re.escape(c) for c in all_codes), re.IGNORECASE),
           {c.lower() for c in para})
    _BREAK_CACHE[key] = hit
    return hit

#: Szybkie rozpoznanie tekstu CJK (japoński, chiński, koreański) — po
#: takich znakach wiersz można łamać w dowolnym miejscu, więc minimalna
#: odległość między przełamaniemiami jest mniejsza niż w tekście łacińskim.
_CJK_DETECT_RE = re.compile(
    "[\u3000-\u30ff\u3400-\u9fff\uf900-\ufaff\uff66-\uff9f\uac00-\ud7af]")


def split_code_structure(text: str | None,
                         line_breaks: Sequence[str] | None = None,
                         para_breaks: Sequence[str] | None = None) -> List[List[Tuple[str, str]]]:
    """Rozbija tekst na akapity i wiersze według podanych kodów.

    Kody akapitowe (domyślnie ``\\p``) zamykają akapit, kody wierszowe
    (domyślnie ``\\n`` / ``\\l``) tylko wiersz — ale lista kodów jest
    DO WYBORU (``line_breaks`` / ``para_breaks``), więc funkcja działa z
    dowolnymi znacznikami użycia danej gry.

    Zwraca listę akapitów; każdy akapit to lista krotek
    ``(treść_wiersza, kod_po_wierszu)`` — kod pustego łańcucha oznacza, że
    wiersz jest ostatni w akapicie. Tekst bez kodów to jeden akapit
    z jednym wierszem.
    """
    if not text:
        return []
    break_re, para_set = _break_tables(line_breaks, para_breaks)
    paragraphs: List[List[Tuple[str, str]]] = []
    lines: List[Tuple[str, str]] = []
    last = 0
    for match in break_re.finditer(text):
        lines.append((text[last:match.start()], match.group()))
        last = match.end()
        if match.group().lower() in para_set:
            paragraphs.append(lines)
            lines = []
    lines.append((text[last:], ""))
    paragraphs.append(lines)
    return paragraphs


def normalize_break_spaces(source: str | None, target: str | None,
                           line_breaks: Sequence[str] | None = None,
                           para_breaks: Sequence[str] | None = None) -> str:
    """Ucina spacje przy kodach wiersza, których nie ma w oryginale.

    Wpis w pamięci bywa zapisany z odstępem przed przełamaniem::

        oryginał:    ...even a crash with a jet\nplane won't leave a scratch.
        wpis w TM:   ...nawet \nzderzenie nie pozostawi zadrapania.
                                ^ spacja, której nie ma w oryginale

    Po wstawieniu taka spacja zostaje w pliku i psuje tekst (w grze widać
    odstęp na początku drugiej linii). Tu przycinamy odstępy przy kodach tak,
    żeby układ zgadzał się z oryginałem — spacja znika tylko wtedy, gdy
    w oryginale też jej nie ma.

    Struktura kodów musi się zgadzać (tyle samo akapitów i wierszy); inaczej
    nie wiadomo, co do czego porównać i tekst zostaje nietknięty.
    """
    if not source or not target:
        return target or ""
    src_paras = split_code_structure(source, line_breaks, para_breaks)
    tgt_paras = split_code_structure(target, line_breaks, para_breaks)
    if len(src_paras) != len(tgt_paras):
        return target
    out: List[str] = []
    for src_par, tgt_par in zip(src_paras, tgt_paras):
        if len(src_par) != len(tgt_par):
            out.append("".join(text + code for text, code in tgt_par))
            continue
        pieces: List[str] = []
        for index, (text, code) in enumerate(tgt_par):
            src_line = src_par[index][0]
            # koniec wiersza: spacja przed kodem
            if index < len(tgt_par) - 1 and text.endswith(" ") \
                    and not src_line.endswith(" "):
                text = text.rstrip(" ")
            # początek wiersza: spacja zaraz po kodzie
            if index > 0 and text.startswith(" ") and not src_line.startswith(" "):
                text = text.lstrip(" ")
            pieces.append(text + code)
        out.append("".join(pieces))
    return "".join(out)

def trim_break_spaces(source: str | None, target: str | None,
                      line_breaks: Sequence[str] | None = None,
                      para_breaks: Sequence[str] | None = None) -> str:
    """Odstępy przy kodach wiersza zgodnie z oryginałem (z wyłącznikiem).

    Wyłącznik: ustawienie ``tm.adapt.break.spaces`` (domyślnie włączone).
    Kiedy ktoś celowo trzyma spację przed ``\\n``, wyłącza opcję — tekst
    z pamięci trafia wtedy do pliku bez żadnych zmian.
    """
    if not source or not target:
        return target or ""
    try:
        from .settings import SettingsManager

        if not SettingsManager.instance().get_bool("tm.adapt.break.spaces", True):
            return target
    except Exception:
        return target
    return normalize_break_spaces(source, target, line_breaks, para_breaks)

def codes_structure_matches(source: str | None, target: str | None,
                            line_breaks: Sequence[str] | None = None,
                            para_breaks: Sequence[str] | None = None) -> bool:
    """Czy tłumaczenie ma TĄ SAMĄ strukturę kodów co oryginał.

    Porównujemy tylko układ (ile akapitów, ile wierszy w akapicie) — nie
    to, który dokładnie znak to przełamał (\\n czy \\l).
    """
    src = split_code_structure(source or "", line_breaks, para_breaks)
    tgt = split_code_structure(target or "", line_breaks, para_breaks)
    if len(src) != len(tgt):
        return False
    for src_par, tgt_par in zip(src, tgt):
        if len(src_par) != len(tgt_par):
            return False
    return True


def _flatten_lines(lines: List[Tuple[str, str]]) -> str:
    """Łączy wiersze w jeden ciąg, wstawiając spację TYLKO w miejscach złącza."""
    parts: List[str] = []
    for text, _code in lines:
        if (parts and text
                and not parts[-1].endswith(_BREAKABLE_AFTER)
                and not text.startswith(_BREAKABLE_AFTER)):
            parts.append(" ")
        parts.append(text)
    return "".join(parts)


def _find_break(text: str, pos: int, window: int) -> Tuple[int, bool]:
    """Miejsce bezpiecznego przełamania w pobliżu ``pos``.

    Zwraca ``(pozycja, czy_zjada_spację)``: przełamanie leży po spacji
    (spacja znika — jej rolę przejmuje kod, jak w oryginale) albo, gdy w
    okolicy nie ma spacji (tekst CJK — można łamać w dowolnym miejscu),
    dokładnie w ``pos``.
    """
    lo = max(0, pos - window)
    hi = min(len(text), pos + window + 1)
    best: Tuple[int, int] | None = None      # (odległość, pozycja)
    i = lo
    while i < hi:
        i = text.find(" ", i)
        if i == -1 or i >= hi:
            break
        dist = abs(i - pos)
        if best is None or dist < best[0]:
            best = (dist, i)
        i += 1
    if best is not None:
        return best[1], True
    return pos, False


#: ---------------- dopasowanie „inteligentne” (po słowach) ----------------
_SMART_WORD_RE = re.compile(r"[^\s]+")
_SMART_STRIP = ".,;:!?'\"()[]{}«»—–-"


def _norm_words(text: str) -> List[str]:
    """Wyrazy do porównywania: bez interpunkcji przy brzegach, małe litery."""
    out: List[str] = []
    for w in _SMART_WORD_RE.findall(text or ""):
        w = w.strip(_SMART_STRIP).casefold()
        if w:
            out.append(w)
    return out


def _counter_jaccard(a: "Counter", b: "Counter") -> float:
    """Podobieństwo dwóch (wielo)zbiorów wyrazów: 0.0–1.0."""
    union = sum((a | b).values())
    if not union:
        return 0.0
    return sum((a & b).values()) / union


def _word_boundary(pos: int, spans: List[Tuple[int, int]]) -> int:
    """Ile wyrazów leży przed pozycją ``pos`` (na granicy przełamania)."""
    b = 0
    for s, _e in spans:
        if s < pos:
            b += 1
        else:
            break
    return b


def _breaks_score(breaks: List[Tuple[int, int]],
                  line_words: List[List[str]],
                  prefix: List["Counter"], m: int) -> float:
    """Suma podobieństwa: wiersze oryginału ↔ kawałki tłumaczenia.

    ``breaks`` — pary (numer wiersza oryginału po którym łamiemy [1..n-1],
    granica w liczbie wyrazów tłumaczenia), rosnąco.
    """
    score = 0.0
    prev_l = prev_w = 0
    for lw, bw in breaks:
        if bw <= prev_w or lw <= prev_l:
            continue
        chunk = prefix[bw] - prefix[prev_w]
        total: Counter = Counter()
        for li in range(prev_l, lw):
            total += Counter(line_words[li])
        score += _counter_jaccard(total, chunk)
        prev_l, prev_w = lw, bw
    if prev_w < m or prev_l < len(line_words):
        total: Counter = Counter()
        for li in range(prev_l, len(line_words)):
            total += Counter(line_words[li])
        score += _counter_jaccard(total, prefix[m] - prefix[prev_w])
    return score


def _smart_breaks_scored(
        text: str, src_par: List[List[Tuple[str, str]]],
        spans: List[Tuple[int, int]], prefix: List["Counter"],
        line_words: List[List[str]]
) -> Tuple[List[Tuple[int, bool, str, int]], float] | None:
    """Przełamania w miejscu, gdzie tłumaczenie ma odpowiednik wiersza oryginału.

    Program „czyta” oba teksty po wyrazach: każdy wiersz oryginału jest
    dopasowany (DP, suma podobieństw maksymalna, granice rosną) do kawałka
    tłumaczenia, a przełamanie stawia tam, gdzie ten kawałek się kończy.
    Zwraca ``(pozycja, zjada_spację, kod, numer_wiersza)`` + wynik dopasowania
    albo ``None``, gdy taki układ jest niemożliwy/brzydki.
    """
    n = len(src_par)
    m = len(spans)
    if not (2 <= n <= 6) or m < n or m > 64:
        return None
    if any(not lw for lw in line_words):
        return None
    line_counters = [Counter(lw) for lw in line_words]
    NEG = float("-inf")
    dp = [[NEG] * (m + 1) for _ in range(n + 1)]
    back = [[-1] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    for i in range(1, n + 1):
        minw = 1 if i == n else 2
        for j in range(minw, m - (n - i) + 1):
            best, bk = NEG, -1
            for k in range(j - minw, -1, -1):
                if dp[i - 1][k] == NEG:
                    continue
                sc = dp[i - 1][k] + _counter_jaccard(
                    line_counters[i - 1], prefix[j] - prefix[k])
                if sc > best:
                    best, bk = sc, k
            dp[i][j] = best
            back[i][j] = bk
    if dp[n][m] == NEG:
        return None
    bounds: List[int] = []
    j = m
    for i in range(n, 1, -1):
        j = back[i][j]
        bounds.append(j)
    bounds.reverse()
    prev_end = 0
    for bi, b in enumerate(bounds):
        s, e = spans[b - 1]
        eats = e < len(text) and text[e] == " "
        if bi < len(bounds) - 1 and e - prev_end < 3:
            return None      # wiersz byłby ułamkiem — lepiej proporcjonalnie
        prev_end = e + (1 if eats else 0)
    if len(text) - prev_end < 3:
        return None          # po ostatnim przełamaniu zostałby ułamek
    breaks: List[Tuple[int, bool, str, int]] = []
    for bi, b in enumerate(bounds):
        s, e = spans[b - 1]
        eats = e < len(text) and text[e] == " "
        breaks.append((e, eats, src_par[bi][1], bi + 1))
    score = _breaks_score(
        [(bi + 1, b) for bi, b in enumerate(bounds)], line_words, prefix, m)
    return breaks, score

def adapt_codes(source: str | None, target: str | None,
                line_breaks: Sequence[str] | None = None,
                para_breaks: Sequence[str] | None = None,
                smart: bool = True) -> str:
    """Dopasowuje znaczniki wiersza/akapitu w tłumaczeniu do oryginału.

    Kody do dopasowania są DO WYBORU (domyślnie wiersz ``\\n``/``\\l``,
    akapit ``\\p``) — patrz ``tm.adapt.line.codes`` / ``tm.adapt.para.codes``;
    inne znaczniki gry podaje się w tych ustawieniach.

    W plikach gier linia dialogu ma określoną szerokość, więc tłumaczenie
    powinno przełamywać się w zbliżonych miejscach jak oryginał. Funkcja:

    * nie rusza tłumaczenia, gdy struktura kodów już się zgadza,
    * przenosi akapity (``\\p``) 1:1 — nadwyżkę dokleja do ostatniego,
    * wiersze rozkłada proporcjonalnie do długości wierszy oryginału,
      przełamując przy najbliższej spacji (w CJK — w miejscu proporcji);
      w trybie inteligentnym (``smart``, domyślnie włączone) program
      pasuje wyrazy tłumaczenia do wierszy oryginału i stawia przełamanie
      tam, gdzie faktycznie leży ich odpowiednik (wygrywa lepszy z
      dwóch układów, ocenionych tym samym kryterium),
    * zachowuje wiodące/końcowe spacje tłumaczenia (wcięcie dialogu).

    Wynik ma te same treść (bez kodów) co wejście, a inną — układ kodów.
    """
    if not source or not target or not target.strip():
        return target or ""
    target = trim_break_spaces(source, target, line_breaks, para_breaks)
    if codes_structure_matches(source, target, line_breaks, para_breaks):
        return target

    src_paras = split_code_structure(source, line_breaks, para_breaks)
    tgt_paras = split_code_structure(target, line_breaks, para_breaks)
    tgt_flat = [_flatten_lines(par) for par in tgt_paras]

    # Wyrównanie liczby akapitów.
    aligned: List[str]
    if len(tgt_flat) == len(src_paras):
        aligned = tgt_flat
    elif len(tgt_flat) > len(src_paras):
        aligned = list(tgt_flat[:len(src_paras) - 1])
        aligned.append(" ".join(t for t in tgt_flat[len(src_paras) - 1:] if t))
    else:
        # Mniej akapitów niż w oryginale — tekst zostaje w pierwszych
        # akapitach, a brakujących \\p nie wymyślamy (zip pomieta resztę).
        aligned = list(tgt_flat)

    out_paras: List[str] = []
    for src_par, text in zip(src_paras, aligned):
        text = text.strip()
        if not text:
            out_paras.append("")
            continue
        if len(src_par) == 1:
            out_paras.append(text)
            continue

        widths = [len(line) for line, _code in src_par]
        total = sum(widths) or 1
        window = max(2, len(text) // (2 * len(src_par)))
        window = min(window, 12)
        cjk_text = bool(_CJK_DETECT_RE.search(text))
        min_gap = 3 if cjk_text else 4
        tail_min = 2 if cjk_text else 3

        prop_breaks: List[Tuple[int, bool, str, int]] = []  # (pozycja, spacja, kod, wiersz)
        consumed = 0
        for idx in range(1, len(src_par)):
            wanted = round(len(text) * (consumed + widths[idx - 1]) / total)
            pos, eats = _find_break(text, wanted, window)
            code = src_par[idx - 1][1]
            consumed += widths[idx - 1]
            if prop_breaks:
                last_end = prop_breaks[-1][0] + (1 if prop_breaks[-1][1] else 0)
                if pos - last_end < min_gap:
                    continue        # wiersz byłby zbyt krótki — kod odpada
            if len(text) - (pos + (1 if eats else 0)) < tail_min:
                continue            # po przełamaniu zostałby ułamek wiersza
            prop_breaks.append((pos, eats, code, idx))

        # Tryb inteligentny: program pasuje wyrazy tłumaczenia do wierszy
        # oryginału i wstawia kod tam, gdzie faktycznie leży ich odpowiednik.
        # Porównujemy oba układy tym samym kryterium i bierzemy lepszy —
        # dopasowanie nigdy nie będzie gorsze niż klasyczna proporcja.
        chosen = prop_breaks
        if smart and not cjk_text:
            spans = [mt.span() for mt in _SMART_WORD_RE.finditer(text)]
            prefix: List[Counter] = [Counter()]
            for s, e in spans:
                prefix.append(prefix[-1] + Counter(_norm_words(text[s:e])))
            line_words = [_norm_words(line) for line, _code in src_par]
            prop_score = _breaks_score(
                [(idx, _word_boundary(pos, spans))
                 for (pos, _eats, _code, idx) in prop_breaks],
                line_words, prefix, len(spans))
            sb = _smart_breaks_scored(text, src_par, spans, prefix, line_words)
            if sb is not None and sb[1] > prop_score + 1e-9:
                chosen = sb[0]

        breaks = [(pos, eats, code) for (pos, eats, code, _idx) in chosen]

        parts: List[str] = []
        start = 0
        for (pos, eats, code) in breaks:
            parts.append(text[start:pos])
            parts.append(code)
            start = pos + 1 if eats else pos
        parts.append(text[start:])
        out_paras.append("".join(parts))

    # Akapity sklejamy kodem, który faktycznie używa tłumaczenie (domyślnie
    # \\p) — z własnymi kodami akapitowymi musi wyjść ten sam znacznik.
    break_re, para_set = _break_tables(line_breaks, para_breaks)
    para_join = (para_breaks[0] if para_breaks else DEFAULT_PARA_BREAKS[0])
    found = break_re.search(target)
    if found is not None and found.group().lower() in para_set:
        para_join = found.group()
    result = para_join.join(out_paras)
    lead, _core, trail = split_edges(target)
    return f"{lead}{result}{trail}"
