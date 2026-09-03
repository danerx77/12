"""Instalacja i uruchamianie własnego serwera LibreTranslate.

LibreTranslate to silnik tłumaczenia działający **na Twoim komputerze** —
bez limitów zapytań i bez wysyłania tekstu w internet. Wymaga jednorazowej
instalacji pakietu (`pip install libretranslate`) oraz pobrania modeli
językowych (kilkaset MB przy pierwszym uruchomieniu).

Moduł jest niezależny od GUI, żeby dało się go przetestować bez Qt.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Callable, List, Optional, Tuple

DEFAULT_PORT = 5000
DEFAULT_HOST = "127.0.0.1"

#: Publiczne serwery LibreTranslate – sprawdzone pod kątem dostępności.
#: Większość wymaga klucza albo bywa wyłączona, dlatego zalecany jest serwer własny.
PUBLIC_SERVERS = [
    ("libretranslate.com (wymaga darmowego klucza)", "https://libretranslate.com"),
    ("libretranslate.de", "https://libretranslate.de"),
    ("translate.terraprint.co", "https://translate.terraprint.co"),
]


def is_installed() -> bool:
    """Czy pakiet `libretranslate` jest zainstalowany w tym Pythonie."""
    try:
        import importlib.util

        return importlib.util.find_spec("libretranslate") is not None
    except Exception:
        return False


def installed_version() -> str:
    """Wersja zainstalowanego pakietu (pusty napis, gdy go nie ma)."""
    try:
        from importlib.metadata import version

        return version("libretranslate")
    except Exception:
        return ""


def subprocess_env() -> dict:
    """Środowisko dla pipa i serwera — z wymuszonym UTF-8.

    **To naprawia najczęstszą awarię na Windowsie.** Modele nazywają się
    ``English → Polish`` (strzałka U+2192). Konsola Windows pracuje domyślnie
    w cp1250/cp852, więc ``print`` z tą nazwą wyrzuca ``UnicodeEncodeError:
    'charmap' codec can't encode character '\u2192'``. LibreTranslate łapie
    ten wyjątek jako „Cannot update models (normal if you're offline)”, przez
    co **modele nie zostają zainstalowane** — a chwilę później serwer przewraca
    się na ``IndexError: list index out of range`` w ``create_app``, bo lista
    języków jest pusta. Wymuszenie UTF-8 usuwa całą tę kaskadę.
    """
    environment = dict(os.environ)
    environment["LT_DISABLE_WEB_UI"] = "false"
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONUTF8"] = "1"          # tryb UTF-8 (PEP 540)
    # `requests` krzyczy ostrzeżeniem, gdy wersje urllib3/chardet nie są tymi,
    # pod które był budowany. To tylko hałas — serwer działa normalnie.
    environment["PYTHONWARNINGS"] = "ignore:::requests"
    return environment


#: Objawy, po których poznajemy, że modele językowe się nie pobrały.
_NO_MODELS_HINTS = ("list index out of range", "language_target_fallback",
                    "IndexError")


def explain_start_error(output: str) -> str:
    """Zamienia wysyp Pythona na zdanie, z którego coś wynika.

    Bez tego użytkownik widzi ``IndexError: list index out of range`` i nie ma
    pojęcia, że chodzi o nieudane pobranie modeli.
    """
    text = output or ""
    if any(hint in text for hint in _NO_MODELS_HINTS):
        message = ("Serwer wystartował bez modeli językowych, dlatego się przewrócił "
                   "(IndexError – pusta lista języków).")
        if "charmap" in text or "UnicodeEncodeError" in text or "\\u2192" in text:
            message += ("\n\nPrzyczyna: konsola Windows nie potrafiła wypisać nazwy "
                        "modelu „English → Polish” (znak →), więc pobieranie zostało "
                        "przerwane. Program wymusza teraz kodowanie UTF-8 — "
                        "kliknij „▶ Uruchom serwer” jeszcze raz.")
        else:
            message += ("\n\nSprawdź połączenie z internetem i kliknij „▶ Uruchom serwer” "
                        "ponownie — modele (ok. 163 MB na parę) pobiorą się od nowa.")
        return message
    if "charmap" in text or "UnicodeEncodeError" in text:
        return ("Błąd kodowania polskich znaków w konsoli. Program wymusza teraz UTF-8 — "
                "spróbuj uruchomić serwer ponownie.")
    if "Address already in use" in text or "10048" in text:
        return ("Port 5000 jest już zajęty przez inny program. Zamknij go albo zatrzymaj "
                "poprzedni serwer LibreTranslate.")
    return ""


def installed_model_pairs() -> List[Tuple[str, str]]:
    """Pary językowe modeli już pobranych na dysk (np. ``[("en","pl")]``)."""
    try:
        from argostranslate import package

        return [(p.from_code, p.to_code) for p in package.get_installed_packages()]
    except Exception:
        return []


def _download_with_progress(url: str, destination: str,
                            on_bytes: Optional[Callable[[int, int], None]] = None,
                            cancelled: Optional[Callable[[], bool]] = None) -> None:
    """Pobiera plik kawałkami, meldując postęp.

    Argos ściąga model **w całości do pamięci** i zapisuje jednym `write`
    na samym końcu (`networking.get()` → `f.write(data)`). Przez to katalog
    modeli nie rośnie w trakcie i pasek postępu stał w miejscu przez kilka
    minut. Dlatego pobieramy sami, strumieniowo, i dopiero gotowy plik
    oddajemy argosowi do instalacji.
    """
    request = urllib.request.Request(url, headers={"User-Agent": "ArgosTranslate"})
    with urllib.request.urlopen(request, timeout=60) as response:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        partial = destination + ".part"
        with open(partial, "wb") as handle:
            while True:
                if cancelled is not None and cancelled():
                    raise RuntimeError("Pobieranie przerwane.")
                chunk = response.read(262144)          # 256 kB
                if not chunk:
                    break
                handle.write(chunk)
                done += len(chunk)
                if on_bytes is not None:
                    on_bytes(done, total)
    os.replace(partial, destination)


def model_download_plan(languages: str = "en,pl") -> Tuple[List, int]:
    """Modele do pobrania i ich łączna waga w bajtach (z nagłówków HTTP)."""
    codes = [c.strip() for c in languages.split(",") if c.strip()]
    if len(codes) < 2:
        return [], 0
    from argostranslate import package

    have = set(installed_model_pairs())
    wanted = {(a, b) for a in codes for b in codes if a != b}
    needed = [p for p in package.get_available_packages()
              if (p.from_code, p.to_code) in wanted
              and (p.from_code, p.to_code) not in have]
    total = 0
    for pack in needed:
        try:
            request = urllib.request.Request(
                pack.links[0], method="HEAD",
                headers={"User-Agent": "ArgosTranslate"})
            with urllib.request.urlopen(request, timeout=20) as response:
                total += int(response.headers.get("Content-Length") or 0)
        except Exception:
            total += LANGUAGE_PAIR_MB * 1024 ** 2 // 2      # ostrożne przybliżenie
    return needed, total


def ensure_models(languages: str = "en,pl",
                  on_output: Optional[Callable[[str], None]] = None,
                  on_bytes: Optional[Callable[[int, int], None]] = None,
                  cancelled: Optional[Callable[[], bool]] = None) -> Tuple[bool, str]:
    """Pobiera modele PRZED startem serwera, w tym samym procesie.

    Serwer uruchamiany jako podproces potrafił „połknąć” błąd pobierania
    i wystartować bez modeli, przewracając się dopiero na ``IndexError``.
    Tutaj robimy to wprost: widać, czy modele są, i dostajemy prawdziwy błąd
    zamiast „normal if you're offline”.
    """
    codes = [c.strip() for c in languages.split(",") if c.strip()]
    if len(codes) < 2:
        return True, ""            # nie ma czego sprawdzać
    have = set(installed_model_pairs())
    wanted = [(a, b) for a in codes for b in codes if a != b]
    if all(pair in have for pair in wanted):
        return True, "Modele są już pobrane."

    try:
        from argostranslate import package, settings

        if on_output is not None:
            on_output("Pobieranie listy modeli…")
        package.update_package_index()
        needed, total_bytes = model_download_plan(languages)
        if not needed and not have:
            return False, (f"Brak modeli dla języków „{languages}”. "
                           "Sprawdź kody języków (np. en,pl).")
        if on_output is not None and total_bytes:
            on_output(f"Do pobrania: {len(needed)} modeli, "
                      f"{format_size(total_bytes)}")

        folder = str(settings.downloads_dir)
        os.makedirs(folder, exist_ok=True)
        grand_done = 0
        for index, pack in enumerate(needed, 1):
            # Nazwa pakietu zawiera znak → – budujemy opis sami, żeby nie
            # zależeć od kodowania konsoli Windows.
            label = f"{pack.from_code} → {pack.to_code}"
            if on_output is not None:
                on_output(f"Pobieranie modelu {index}/{len(needed)}: {label}…")
            target = os.path.join(
                folder, f"translate-{pack.from_code}_{pack.to_code}.argosmodel")

            def report(done: int, size: int, _base=grand_done, _l=label,
                       _i=index, _n=len(needed)) -> None:
                if on_bytes is not None:
                    on_bytes(_base + done, total_bytes or size)
                if on_output is not None and size:
                    on_output(f"Model {_i}/{_n} ({_l}): "
                              f"{format_size(done)} / {format_size(size)}")

            _download_with_progress(pack.links[0], target, report, cancelled)
            grand_done += os.path.getsize(target)
            if on_output is not None:
                on_output(f"Instalowanie modelu {index}/{len(needed)}: {label}…")
            package.install_from_path(target)
            try:
                os.remove(target)
            except OSError:
                pass
        return True, f"Pobrano modele: {len(needed)} ({format_size(grand_done)})."
    except Exception as exc:
        return False, (f"Nie udało się pobrać modeli językowych: {exc}\n"
                       "Sprawdź połączenie z internetem.")


def dependency_warning_info() -> Tuple[bool, str]:
    """Sprawdza znane ostrzeżenie `RequestsDependencyWarning`.

    Biblioteka `requests` przy imporcie porównuje wersje `urllib3` i `chardet`
    z tym, pod co była budowana. Nowszy `chardet` (7.x) wykracza poza
    deklarowane `chardet <6`, więc `requests` wypisuje ostrzeżenie — **ale
    działa normalnie**, co sprawdziliśmy zapytaniem HTTP. To kosmetyka, nie awaria.

    Zwraca ``(czy_występuje, opis)``.
    """
    try:
        from importlib.metadata import version

        requests_version = version("requests")
    except Exception:
        return False, ""
    try:
        from importlib.metadata import version

        chardet_version = version("chardet")
    except Exception:
        chardet_version = ""
    if not chardet_version:
        return False, ""
    try:
        major = int(chardet_version.split(".")[0])
    except ValueError:
        return False, ""
    if major >= 6:
        return True, (
            f"Masz chardet {chardet_version}, a requests {requests_version} deklaruje "
            "zgodność z chardet poniżej 6. Dlatego przy każdym uruchomieniu pojawia "
            "się „RequestsDependencyWarning”. To tylko ostrzeżenie — pobieranie "
            "i tłumaczenie działają normalnie.\n"
            "Można je usunąć poleceniem:\n\n"
            "    pip install -U requests\n\n"
            "albo odinstalowując zbędny pakiet:\n\n"
            "    pip uninstall chardet"
        )
    return False, ""


#: Katalog języków zapamiętany na czas sesji (pobranie listy wymaga sieci).
_LANGUAGE_CACHE: Optional[List[dict]] = None


def language_catalog(refresh: bool = False) -> List[dict]:
    """Lista języków obsługiwanych przez LibreTranslate.

    Zwraca słowniki ``{code, name, installed, pairs, bytes}``:
    czy modele dla danego języka są już na dysku, ile par go dotyczy
    i ile waży komplet. Wynik jest zapamiętywany, bo odpytanie repozytorium
    trwa chwilę i wymaga internetu.
    """
    global _LANGUAGE_CACHE
    if _LANGUAGE_CACHE is not None and not refresh:
        return _LANGUAGE_CACHE
    try:
        from argostranslate import package

        if refresh or not package.get_available_packages():
            package.update_package_index()
        available = package.get_available_packages()
    except Exception:
        return _LANGUAGE_CACHE or []

    installed = set(installed_model_pairs())
    names: dict = {}
    for pack in available:
        names.setdefault(pack.from_code, getattr(pack, "from_name", pack.from_code))
        names.setdefault(pack.to_code, getattr(pack, "to_name", pack.to_code))

    catalog: List[dict] = []
    for code, name in sorted(names.items(), key=lambda kv: kv[1].lower()):
        pairs = [p for p in available if p.from_code == code or p.to_code == code]
        has = any((p.from_code, p.to_code) in installed for p in pairs)
        catalog.append({
            "code": code,
            "name": name,
            "installed": has,
            "pairs": len(pairs),
        })
    _LANGUAGE_CACHE = catalog
    return catalog


def plural_pairs(count: int) -> str:
    """Polska odmiana rzeczownika „para”: 1 para, 2 pary, 5 par."""
    if count == 1:
        return "1 para"
    last, last_two = count % 10, count % 100
    if 2 <= last <= 4 and not 12 <= last_two <= 14:
        return f"{count} pary"
    return f"{count} par"


def installed_language_codes() -> List[str]:
    """Kody języków, dla których modele są już pobrane."""
    codes: set = set()
    for source, target in installed_model_pairs():
        codes.add(source)
        codes.add(target)
    return sorted(codes)


def describe_state() -> str:
    """Jednozdaniowe podsumowanie stanu – używane przez przycisk „Sprawdź”."""
    if not is_installed():
        return "Pakiet „libretranslate” nie jest zainstalowany."
    parts = [f"pakiet {installed_version()}"]
    codes = installed_language_codes()
    parts.append(f"modele: {', '.join(codes)}" if codes else "brak modeli")
    size = models_size_bytes()
    if size:
        parts.append(format_size(size))
    parts.append("serwer działa" if is_running() else "serwer zatrzymany")
    return "  •  ".join(parts)


def launch_command() -> List[str]:
    """Buduje polecenie startu serwera.

    ``python -m libretranslate`` **nie działa** — pakiet nie ma pliku
    ``__main__.py``, więc Python odpowiada „libretranslate is a package and
    cannot be directly executed”. Poprawne są dwie drogi: skrypt konsolowy
    ``libretranslate`` tworzony przez pipa albo moduł ``libretranslate.main``.
    Skrypt jest pewniejszy (nie wypisuje ostrzeżenia ``runpy``), więc próbujemy
    go najpierw, a moduł zostaje jako zapas.
    """
    import shutil

    script = shutil.which("libretranslate")
    if not script:
        # pip instaluje skrypty obok interpretera (venv) albo w --user
        for folder in (os.path.dirname(sys.executable),
                       os.path.join(os.path.dirname(sys.executable), "Scripts")):
            for name in ("libretranslate", "libretranslate.exe"):
                candidate = os.path.join(folder, name)
                if os.path.isfile(candidate):
                    script = candidate
                    break
            if script:
                break
    if script:
        return [script]
    return [sys.executable, "-m", "libretranslate.main"]


def latest_version(timeout: float = 10.0) -> str:
    """Najnowsza wersja pakietu według PyPI (pusty napis przy braku sieci)."""
    try:
        request = urllib.request.Request(
            "https://pypi.org/pypi/libretranslate/json",
            headers={"User-Agent": "SuperCAT"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return str(json.load(response)["info"]["version"])
    except Exception:
        return ""


def server_url(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> str:
    return f"http://{host}:{port}"


def is_running(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
               timeout: float = 2.0) -> bool:
    """Sprawdza, czy serwer odpowiada pod wskazanym adresem."""
    try:
        request = urllib.request.Request(f"{server_url(host, port)}/languages")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        return isinstance(data, list) and len(data) > 0
    except Exception:
        return False


def available_languages(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> List[str]:
    """Kody języków obsługiwanych przez uruchomiony serwer."""
    try:
        request = urllib.request.Request(f"{server_url(host, port)}/languages")
        with urllib.request.urlopen(request, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
        return [item.get("code", "") for item in data if item.get("code")]
    except Exception:
        return []


def models_dir() -> str:
    """Katalog, w którym argos-translate trzyma pobrane modele językowe."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(
            os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "argos-translate")


def models_size_bytes() -> int:
    """Łączna waga pobranych modeli w bajtach (0, gdy nic jeszcze nie ma)."""
    total = 0
    for root, _dirs, files in os.walk(models_dir()):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def format_size(num_bytes: float) -> str:
    """Waga po ludzku: „163 MB”, „1,42 GB” — z polskim przecinkiem."""
    if num_bytes >= 1024 ** 3:
        return f"{num_bytes / 1024 ** 3:.2f} GB".replace(".", ",")
    if num_bytes >= 1024 ** 2:
        return f"{num_bytes / 1024 ** 2:.0f} MB"
    if num_bytes >= 1024:
        return f"{num_bytes / 1024:.0f} kB"
    return f"{int(num_bytes)} B"


#: Wagi zmierzone na żywo: pakiet ~1,1 MB + zależności, para en+pl to 163 MB modeli.
PACKAGE_SIZE_MB = 1.1
LANGUAGE_PAIR_MB = 163
FULL_SET_GB = 4.0

#: „Downloading nazwa-1.2.3.whl (12.3 MB)” – rozmiar pobieranego pakietu.
_PIP_DOWNLOAD_RE = re.compile(
    r"Downloading\s+(\S+?)\s+\(([\d.]+)\s*([kKMG]i?B)\)")
#: „   |████████ | 5.2/12.3 MB 3.1 MB/s” – postęp pojedynczego pliku.
_PIP_BYTES_RE = re.compile(r"([\d.]+)/([\d.]+)\s*(kB|MB|GB)")


def parse_pip_progress(line: str) -> Optional[Tuple[int, str]]:
    """Wyciąga z wiersza pipa procent i opis – do paska postępu.

    pip nie ma trybu maszynowego, więc czytamy to, co i tak wypisuje:
    nazwę pobieranego pakietu z wagą oraz licznik „5.2/12.3 MB”.
    """
    match = _PIP_BYTES_RE.search(line)
    if match:
        done, total, unit = float(match.group(1)), float(match.group(2)), match.group(3)
        if total > 0:
            percent = max(0, min(100, int(done / total * 100)))
            return percent, f"Pobieranie: {done:.1f}/{total:.1f} {unit}"
    match = _PIP_DOWNLOAD_RE.search(line)
    if match:
        return -1, f"Pobieranie {match.group(1)} ({match.group(2)} {match.group(3)})"
    if line.startswith("Installing collected packages"):
        return 95, "Instalowanie pakietów…"
    if line.startswith("Successfully installed"):
        return 100, "Zainstalowano"
    return None


def install(on_output: Optional[Callable[[str], None]] = None,
            cancelled: Optional[Callable[[], bool]] = None,
            on_progress: Optional[Callable[[int, str], None]] = None) -> Tuple[bool, str]:
    """Instaluje pakiet `libretranslate` przez pip. Zwraca (sukces, komunikat).

    `on_output` dostaje kolejne wiersze z konsoli pipa – dzięki temu okno
    pokazuje postęp zamiast zamierać na kilka minut.
    """
    if is_installed():
        return True, f"Pakiet jest już zainstalowany (wersja {installed_version()})."

    command = [sys.executable, "-m", "pip", "install", "--no-input", "libretranslate"]
    try:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            env=subprocess_env(),
        )
    except Exception as exc:
        return False, f"Nie udało się uruchomić pip: {exc}"

    tail: List[str] = []
    try:
        for line in process.stdout or []:
            line = line.rstrip()
            if not line:
                continue
            tail.append(line)
            del tail[:-40]
            if on_output is not None:
                on_output(line)
            if on_progress is not None:
                step = parse_pip_progress(line)
                if step is not None:
                    on_progress(*step)
            if cancelled is not None and cancelled():
                process.terminate()
                return False, "Instalacja przerwana."
        process.wait(timeout=60)
    except Exception as exc:
        return False, f"Błąd instalacji: {exc}"

    if process.returncode == 0 and is_installed():
        return True, f"Zainstalowano LibreTranslate {installed_version()}."
    return False, "Instalacja nie powiodła się:\n" + "\n".join(tail[-8:])


class LibreTranslateServer:
    """Zarządza procesem lokalnego serwera LibreTranslate."""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
        self.host = host
        self.port = port
        self.process: Optional[subprocess.Popen] = None
        self.last_error = ""
        self.log: List[str] = []

    @property
    def url(self) -> str:
        return server_url(self.host, self.port)

    def start(self, languages: str = "en,pl",
              on_output: Optional[Callable[[str], None]] = None,
              wait_seconds: int = 240) -> Tuple[bool, str]:
        """Uruchamia serwer i czeka, aż zacznie odpowiadać.

        `languages` ogranicza pobierane modele – pełny zestaw to kilka GB,
        a do pracy wystarczy para językowa projektu.
        """
        if is_running(self.host, self.port):
            return True, "Serwer już działa."
        if not is_installed():
            return False, "Pakiet „libretranslate” nie jest zainstalowany."

        # Modele pobieramy sami, zanim wystartuje serwer – inaczej cichy błąd
        # pobierania kończy się niezrozumiałym „IndexError” z wnętrza pakietu.
        ok_models, models_message = ensure_models(languages, on_output)
        if not ok_models:
            return False, models_message

        command = launch_command() + ["--host", self.host, "--port", str(self.port)]
        if languages:
            command += ["--load-only", languages]
        # Bez tego serwer przy pierwszym starcie prosi o potwierdzenie licencji.
        environment = subprocess_env()

        try:
            self.process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                env=environment,
            )
        except Exception as exc:
            self.last_error = str(exc)
            return False, f"Nie udało się uruchomić serwera: {exc}"

        # Pierwszy start pobiera modele językowe – może potrwać kilka minut.
        started = time.monotonic()
        while time.monotonic() - started < wait_seconds:
            if self.process.poll() is not None:
                output = ""
                try:
                    output = (self.process.stdout.read() or "")[-500:]
                except Exception:
                    pass
                self.last_error = output
                hint = explain_start_error(output)
                if hint:
                    return False, f"{hint}\n\nSzczegóły techniczne:\n{output[-300:]}"
                return False, f"Serwer zakończył się przedwcześnie.\n{output}"
            if is_running(self.host, self.port, timeout=1.5):
                return True, f"Serwer działa pod adresem {self.url}"
            if on_output is not None:
                elapsed = int(time.monotonic() - started)
                on_output(f"Uruchamianie… {elapsed}s (pierwszy raz pobiera modele językowe)")
            time.sleep(2.0)

        return False, ("Serwer nie odpowiedział w wyznaczonym czasie. "
                       "Pobieranie modeli może trwać dłużej – spróbuj ponownie za chwilę.")

    def stop(self) -> bool:
        """Zatrzymuje serwer uruchomiony przez program."""
        if self.process is None:
            return False
        try:
            self.process.terminate()
            self.process.wait(timeout=10)
        except Exception:
            try:
                self.process.kill()
            except Exception:
                pass
        finally:
            self.process = None
        return True

    @property
    def is_ours(self) -> bool:
        """Czy to nasz proces (a nie serwer uruchomiony ręcznie przez użytkownika)."""
        return self.process is not None and self.process.poll() is None
