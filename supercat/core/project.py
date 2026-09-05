"""Model projektu i menedżer projektów.

Odpowiednik models/Project.java + services/ProjectManager.java + RecentProjectsManager.java
Plik projektu ma rozszerzenie .scproj (JSON).
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from .settings import APP_DIR

PROJECT_EXT = ".scproj"
PROJECT_FOLDERS = ("source", "target", "tm", "glossary", "dictionary", "export")
RECENT_FILE = os.path.join(APP_DIR, "recent_projects.json")
MAX_RECENT = 10


@dataclass
class SegmentationSettings:
    enabled: bool = True
    mode: str = "sentence"  # sentence | line | paragraph | custom_delimiter | regex
    delimiters: str = ".!?:;"
    custom_delimiter: str = "<<KON>>"
    regex_pattern: str = ""
    merge_empty_lines: bool = True
    treat_paragraph_as_segment: bool = False
    #: Zachowuj spacje/tabulatory na początku i końcu wiersza tak, jak w pliku.
    #: W plikach gier wiodąca spacja to wcięcie dialogu – jej utrata psuje wygląd
    #: tekstu w grze, dlatego domyślnie jest zachowywana.
    preserve_whitespace: bool = True
    #: Własne skróty (po nich kropka NIE kończy zdania), oddzielone przecinkami.
    custom_abbreviations: str = ""
    #: Nie dziel zdania po kropce, gdy dalej jest mała litera (jak w OmegaT).
    require_uppercase_after: bool = True
    #: Nie dziel, gdy przed kropką jest liczba (np. „w 1999. roku”).
    skip_after_numbers: bool = True
    #: Traktuj znaczniki \\n, \\p jako granicę segmentu (pliki gier).
    split_on_codes: bool = False
    #: Minimalna długość segmentu w znakach – krótsze doklejane do poprzedniego.
    min_segment_length: int = 0


@dataclass
class TMSettings:
    enabled: bool = True
    fuzzy_threshold: int = 70
    max_results: int = 10
    auto_add_to_tm: bool = True
    use_external_tm: bool = True


@dataclass
class MTSettings:
    enabled: bool = False
    engine: str = "local"
    formality: str = "default"


@dataclass
class GlossarySettings:
    enabled: bool = True
    auto_suggest: bool = True
    highlight_terms: bool = True


@dataclass
class SpellcheckSettings:
    enabled: bool = True
    dictionary_language: str = "pl_PL"
    underline_errors: bool = True


def order_files(files: List[str], preferred: List[str]) -> List[str]:
    """Układa pliki wg ręcznej kolejności; nieznane trafiają na koniec.

    `preferred` to lista nazw ustawiona przez użytkownika. Pliki, których tam
    nie ma (bo doszły później), dopisujemy alfabetycznie na końcu — import
    nowego pliku nie może przestawiać tego, co użytkownik już poukładał.
    Nazwy z listy, których nie ma już na dysku, są pomijane.
    """
    if not preferred:
        return list(files)
    available = list(files)
    ordered = [name for name in preferred if name in available]
    rest = sorted(name for name in available if name not in set(ordered))
    return ordered + rest


@dataclass
class Project:
    name: str = ""
    source_lang: str = "en"
    target_lang: str = "pl"
    project_path: str = ""
    created_date: float = field(default_factory=time.time)
    modified_date: float = field(default_factory=time.time)
    current_segment_index: int = 0
    source_files: List[str] = field(default_factory=list)
    #: Ręcznie ustawiona kolejność plików (nazwy). Pliki spoza listy trafiają
    #: na koniec, alfabetycznie — dzięki temu nowy import niczego nie przestawia.
    file_order: List[str] = field(default_factory=list)
    #: Zaimportowane pamięci (pliki TMX) – nazwa, ścieżka, liczba jednostek
    tm_sources: List[dict] = field(default_factory=list)
    segmentation: SegmentationSettings = field(default_factory=SegmentationSettings)
    #: Reguły wykluczania segmentów z tłumaczenia (zapisywane w .scproj)
    exclusions: Dict[str, Any] = field(default_factory=dict)
    #: Własne znaczniki plików (nazwa pliku -> "ok"/"warn"/"bad")
    file_markers: Dict[str, str] = field(default_factory=dict)
    tm: TMSettings = field(default_factory=TMSettings)
    mt: MTSettings = field(default_factory=MTSettings)
    glossary: GlossarySettings = field(default_factory=GlossarySettings)
    spellcheck: SpellcheckSettings = field(default_factory=SpellcheckSettings)

    # --- ścieżki --------------------------------------------------------
    @property
    def source_path(self) -> str:
        return os.path.join(self.project_path, "source")

    @property
    def target_path(self) -> str:
        return os.path.join(self.project_path, "target")

    @property
    def tm_path(self) -> str:
        return os.path.join(self.project_path, "tm")

    @property
    def glossary_path(self) -> str:
        return os.path.join(self.project_path, "glossary")

    @property
    def dictionary_path(self) -> str:
        return os.path.join(self.project_path, "dictionary")

    @property
    def export_path(self) -> str:
        return os.path.join(self.project_path, "export")

    @property
    def project_file_path(self) -> str:
        safe = re.sub(r"\s+", "_", self.name or "projekt")
        return os.path.join(self.project_path, safe + PROJECT_EXT)

    # --- serializacja ---------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Project":
        proj = Project()
        for key, value in data.items():
            if key == "segmentation":
                proj.segmentation = SegmentationSettings(**value)
            elif key == "tm":
                proj.tm = TMSettings(**value)
            elif key == "mt":
                proj.mt = MTSettings(**value)
            elif key == "glossary":
                proj.glossary = GlossarySettings(**value)
            elif key == "spellcheck":
                proj.spellcheck = SpellcheckSettings(**value)
            elif hasattr(proj, key):
                setattr(proj, key, value)
        return proj


class ProjectManager:
    """Singleton zarządzający aktualnym projektem."""

    _instance: "ProjectManager | None" = None

    def __init__(self) -> None:
        self.current: Optional[Project] = None

    @classmethod
    def instance(cls) -> "ProjectManager":
        if cls._instance is None:
            cls._instance = ProjectManager()
        return cls._instance

    # ------------------------------------------------------------------
    def create_project(self, name: str, source_lang: str, target_lang: str, base_path: str) -> Project:
        folder_name = re.sub(r"\s+", "_", name.strip())
        project_dir = os.path.join(base_path, folder_name)
        if os.path.exists(project_dir):
            raise FileExistsError("Projekt o tej nazwie już istnieje w tej lokalizacji.")

        os.makedirs(project_dir)
        for folder in PROJECT_FOLDERS:
            os.makedirs(os.path.join(project_dir, folder), exist_ok=True)

        project = Project(
            name=name.strip(),
            source_lang=source_lang,
            target_lang=target_lang,
            project_path=project_dir,
        )
        self.current = project
        self._write_readme(project)
        self.save_project()
        RecentProjects.add(project.project_file_path)
        return project

    def _write_readme(self, project: Project) -> None:
        readme = (
            "=== PROJEKT SuperCAT ===\n\n"
            f"Nazwa projektu: {project.name}\n"
            f"Język źródłowy: {project.source_lang}\n"
            f"Język docelowy: {project.target_lang}\n\n"
            "=== STRUKTURA FOLDERÓW ===\n"
            "- source/     – pliki do tłumaczenia (txt, docx, xlsx, xliff, po, srt, html)\n"
            "- target/     – tutaj trafiają przetłumaczone pliki\n"
            "- tm/         – pliki TMX oraz baza project_tm.db\n"
            "- glossary/   – glosariusz (project_glossary.csv)\n"
            "- dictionary/ – słowniki (pliki .dic / .txt)\n"
            "- export/     – eksporty (XLIFF, TMX, HTML, raporty QA)\n\n"
            f"Utworzono: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        )
        with open(os.path.join(project.project_path, "README.txt"), "w", encoding="utf-8") as fh:
            fh.write(readme)

    # ------------------------------------------------------------------
    def open_project(self, project_file: str) -> Project:
        if not os.path.exists(project_file):
            raise FileNotFoundError("Plik projektu nie istnieje.")
        with open(project_file, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        project = Project.from_dict(data)
        # ścieżka mogła się zmienić (przeniesiony projekt)
        project.project_path = os.path.dirname(os.path.abspath(project_file))
        self.current = project
        self.ensure_structure()
        RecentProjects.add(project_file)
        return project

    def ensure_structure(self) -> None:
        if not self.current:
            return
        for folder in PROJECT_FOLDERS:
            os.makedirs(os.path.join(self.current.project_path, folder), exist_ok=True)

    def save_project(self) -> None:
        if not self.current:
            raise RuntimeError("Brak otwartego projektu.")
        self.current.modified_date = time.time()
        os.makedirs(self.current.project_path, exist_ok=True)
        with open(self.current.project_file_path, "w", encoding="utf-8") as fh:
            json.dump(self.current.to_dict(), fh, ensure_ascii=False, indent=2)

    def close_project(self) -> None:
        self.current = None

    @property
    def is_open(self) -> bool:
        return self.current is not None


class RecentProjects:
    """Lista ostatnio otwieranych projektów."""

    @staticmethod
    def _load() -> List[str]:
        try:
            if os.path.exists(RECENT_FILE):
                with open(RECENT_FILE, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, list):
                    return [p for p in data if isinstance(p, str)]
        except Exception:
            pass
        return []

    @staticmethod
    def _write(items: List[str]) -> None:
        try:
            os.makedirs(APP_DIR, exist_ok=True)
            with open(RECENT_FILE, "w", encoding="utf-8") as fh:
                json.dump(items[:MAX_RECENT], fh, ensure_ascii=False, indent=2)
        except Exception:
            pass

    @classmethod
    def get(cls) -> List[str]:
        return [p for p in cls._load() if os.path.exists(p)]

    @classmethod
    def add(cls, path: str) -> None:
        items = cls._load()
        path = os.path.abspath(path)
        if path in items:
            items.remove(path)
        items.insert(0, path)
        cls._write(items)

    @classmethod
    def clear(cls) -> None:
        cls._write([])
