"""Centralny rejestr skrótów klawiszowych.

Każdy skrót jest zdefiniowany DOKŁADNIE RAZ. Wcześniej te same kombinacje
rejestrowano dwukrotnie – jako `QShortcut` w edytorze i jako akcję menu –
przez co Qt wykrywało niejednoznaczność i **nie uruchamiało żadnej z nich**
(tak przestał działać `Ctrl+U`).

Ustawienia użytkownika trzymane są w `~/.supercat/settings.json` pod kluczem
`shortcut.<identyfikator>`, więc każdy skrót można zmienić w Ustawieniach.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class ShortcutDef:
    """Opis pojedynczego skrótu."""

    key: str            # identyfikator wewnętrzny
    default: str        # domyślna kombinacja klawiszy
    label: str          # nazwa pokazywana użytkownikowi
    group: str          # sekcja w Ustawieniach
    editor: bool = True   # czy działa w edytorze (QShortcut), czy tylko w menu

    @property
    def setting_name(self) -> str:
        return f"shortcut.{self.key}"


#: Wszystkie skróty programu. Kolejność = kolejność w Ustawieniach.
SHORTCUTS: List[ShortcutDef] = [
    # --- plik i projekt ---
    ShortcutDef("new_project", "Ctrl+N", "Nowy projekt", "Plik", editor=False),
    ShortcutDef("open_project", "Ctrl+O", "Otwórz projekt", "Plik", editor=False),
    ShortcutDef("save_all", "Ctrl+S", "Zapisz wszystko", "Plik", editor=False),
    ShortcutDef("import_files", "Ctrl+I", "Importuj pliki", "Plik", editor=False),
    ShortcutDef("export_files", "Ctrl+E", "Eksportuj tłumaczenia", "Plik", editor=False),
    ShortcutDef("reload_source", "F5", "Przeładuj pliki źródłowe", "Plik", editor=False),
    ShortcutDef("close_project", "Ctrl+W", "Zamknij projekt", "Plik", editor=False),
    ShortcutDef("quit", "Ctrl+Q", "Zakończ program", "Plik", editor=False),

    # --- nawigacja ---
    ShortcutDef("next_segment", "Ctrl+PgDown", "Następny segment", "Nawigacja"),
    ShortcutDef("prev_segment", "Ctrl+PgUp", "Poprzedni segment", "Nawigacja"),
    ShortcutDef("next_untranslated", "Ctrl+U", "Następny nieprzetłumaczony", "Nawigacja"),
    ShortcutDef("prev_untranslated", "Ctrl+Shift+U", "Poprzedni nieprzetłumaczony", "Nawigacja"),
    ShortcutDef("next_translated", "Ctrl+Shift+Y", "Następny przetłumaczony", "Nawigacja"),
    ShortcutDef("next_unapproved", "Ctrl+Shift+A", "Następny niezatwierdzony", "Nawigacja"),
    ShortcutDef("first_segment", "Ctrl+Home", "Pierwszy segment", "Nawigacja"),
    ShortcutDef("last_segment", "Ctrl+End", "Ostatni segment", "Nawigacja"),

    # --- tłumaczenie ---
    ShortcutDef("undo", "Ctrl+Z", "Cofnij (tekst i oznaczenia)", "Tłumaczenie", editor=False),
    ShortcutDef("redo", "Ctrl+Y", "Ponów", "Tłumaczenie", editor=False),
    ShortcutDef("confirm_next", "Ctrl+Return", "Zatwierdź segment i przejdź dalej", "Tłumaczenie"),
    ShortcutDef("copy_source", "Ctrl+D", "Kopiuj źródło do tłumaczenia", "Tłumaczenie"),
    ShortcutDef("insert_match", "Ctrl+Space", "Wstaw najlepsze dopasowanie TM", "Tłumaczenie"),
    ShortcutDef("machine_translate", "Ctrl+M", "Tłumaczenie maszynowe segmentu", "Tłumaczenie"),
    ShortcutDef("save_to_tm", "Ctrl+Shift+S", "Zapisz segment do pamięci TM", "Tłumaczenie"),
    ShortcutDef("restore_indent", "Ctrl+Shift+W", "Przywróć wcięcie ze źródła", "Tłumaczenie"),

    # --- oznaczenia ---
    ShortcutDef("mark_new", "Ctrl+Shift+1", "Oznacz jako nowy", "Oznaczenia"),
    ShortcutDef("mark_draft", "Ctrl+Shift+2", "Oznacz jako roboczy", "Oznaczenia"),
    ShortcutDef("mark_todo", "Ctrl+Shift+T", "Oznacz jako „do przetłumaczenia”", "Oznaczenia"),
    ShortcutDef("mark_translated", "Ctrl+Shift+3", "Oznacz jako przetłumaczony", "Oznaczenia"),
    ShortcutDef("next_todo", "Ctrl+Shift+G", "Następny „do przetłumaczenia”", "Nawigacja"),
    ShortcutDef("mark_approved", "Ctrl+Shift+4", "Oznacz jako zatwierdzony", "Oznaczenia"),
    ShortcutDef("ignore_selected", "Ctrl+Shift+I", "Pomiń zaznaczone segmenty", "Oznaczenia"),
    ShortcutDef("restore_selected", "Ctrl+Shift+R", "Przywróć zaznaczone segmenty", "Oznaczenia"),

    # --- narzędzia ---
    ShortcutDef("find_replace", "Ctrl+F", "Znajdź i zamień", "Narzędzia", editor=False),
    ShortcutDef("find_selected", "Ctrl+Shift+F", "Szukaj zaznaczonego wyrazu", "Narzędzia"),
    ShortcutDef("find_in_file", "Ctrl+Shift+E", "Szukaj w bieżącym pliku", "Narzędzia"),
    ShortcutDef("next_result", "F3", "Następny wynik wyszukiwania", "Narzędzia"),
    ShortcutDef("prev_result", "Shift+F3", "Poprzedni wynik wyszukiwania", "Narzędzia"),
    ShortcutDef("check_language", "Ctrl+Shift+J", "Sprawdź poprawność języka", "Narzędzia"),
    ShortcutDef("quicktrans", "Ctrl+Shift+Q", "QuickTrans – porównanie silników", "Narzędzia", editor=False),
    ShortcutDef("tmx_editor", "Ctrl+Shift+X", "Edytor pamięci TMX", "Narzędzia", editor=False),
    ShortcutDef("copy_timing", "Ctrl+Shift+P", "Kopiuj pomiar czasu", "Narzędzia"),
    ShortcutDef("run_qa", "F8", "Uruchom kontrolę QA", "Narzędzia", editor=False),
    ShortcutDef("statistics", "F9", "Statystyki projektu", "Narzędzia", editor=False),
    ShortcutDef("new_search_window", "Ctrl+Shift+N", "Nowe okno wyszukiwania", "Narzędzia", editor=False),

    # --- widok i pomoc ---
    ShortcutDef("toggle_sentence", "Ctrl+Shift+M", "Dopasowanie zdań (włącz/wyłącz)", "Widok", editor=False),
    ShortcutDef("toggle_theme", "Ctrl+T", "Przełącz motyw (ciemny/jasny)", "Widok", editor=False),
    ShortcutDef("font_plus", "Ctrl++", "Powiększ czcionkę edytora", "Widok", editor=False),
    ShortcutDef("font_minus", "Ctrl+-", "Zmniejsz czcionkę edytora", "Widok", editor=False),
    ShortcutDef("ui_font_plus", "Ctrl+Shift++", "Powiększ czcionkę interfejsu", "Widok", editor=False),
    ShortcutDef("ui_font_minus", "Ctrl+Shift+-", "Zmniejsz czcionkę interfejsu", "Widok", editor=False),
    ShortcutDef("about", "F1", "O programie / skróty klawiszowe", "Pomoc", editor=False),
]

BY_KEY: Dict[str, ShortcutDef] = {s.key: s for s in SHORTCUTS}

#: Litery, które na polskiej klawiaturze powstają z AltGr (czyli Ctrl+Alt
#: w Qt): ą ć ę ł ń ó ś ź ż. Skrót „Alt + dowolna litera” sprawia, że zamiast
#: polskiego znaku uruchamia się polecenie — Qt widzi AltGr jako Ctrl+Alt.
_POLISH_ALTGR_LETTERS = set("acelnosxz")


def blocks_polish_letters(sequence: str) -> bool:
    """Czy kombinacja wyłapuje wpisywanie polskiego znaku.

    Na polskiej klawiaturze AltGr+E to „ę”, a Qt widzi to jako ``Ctrl+Alt+E``.
    Skrót o takiej kombinacji „zjada” literę — dlatego żaden domyślny skrót
    programu nie używa Alt z literą (Alt+strzałka jest w porządku).
    """
    parts = [p.strip().lower() for p in (sequence or "").split("+") if p.strip()]
    if not parts or "alt" not in parts:
        return False
    key = parts[-1]
    return len(key) == 1 and key.isalpha()


def groups() -> List[str]:
    """Nazwy sekcji w kolejności występowania."""
    out: List[str] = []
    for shortcut in SHORTCUTS:
        if shortcut.group not in out:
            out.append(shortcut.group)
    return out


def get(key: str, settings=None) -> str:
    """Aktualna kombinacja dla skrótu (z ustawień albo domyślna)."""
    definition = BY_KEY.get(key)
    if definition is None:
        return ""
    if settings is None:
        try:
            from .settings import SettingsManager

            settings = SettingsManager.instance()
        except Exception:
            return definition.default
    value = settings.get(definition.setting_name, "")
    return value if value else definition.default


def set_key(key: str, sequence: str, settings=None) -> None:
    """Zapisuje własną kombinację (pusta = przywrócenie domyślnej)."""
    definition = BY_KEY.get(key)
    if definition is None:
        return
    if settings is None:
        from .settings import SettingsManager

        settings = SettingsManager.instance()
    settings.set(definition.setting_name, (sequence or "").strip())


def reset_all(settings=None) -> None:
    """Przywraca domyślne kombinacje dla wszystkich skrótów."""
    if settings is None:
        from .settings import SettingsManager

        settings = SettingsManager.instance()
    for definition in SHORTCUTS:
        settings.set(definition.setting_name, "")


def current_map(settings=None) -> Dict[str, str]:
    return {s.key: get(s.key, settings) for s in SHORTCUTS}


def with_shortcut(key: str, text: str, settings=None) -> str:
    """Dokleja aktualną kombinację do podpowiedzi, np. ``Zapisz (Ctrl+S)``."""
    sequence = get(key, settings)
    if not sequence:
        return text
    if sequence in text:
        return text
    return f"{text} ({sequence})"


def find_conflict(key: str, sequence: str, settings=None) -> Optional[str]:
    """Zwraca nazwę polecenia, które już używa tej kombinacji (albo None)."""
    sequence = (sequence or "").strip()
    if not sequence:
        return None
    for definition in SHORTCUTS:
        if definition.key == key:
            continue
        if get(definition.key, settings).lower() == sequence.lower():
            return definition.label
    return None
