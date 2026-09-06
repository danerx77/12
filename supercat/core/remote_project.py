"""Pobieranie projektu tłumaczenia z internetu (GitHub / Git) — jak zespół w OmegaT."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from typing import Optional, Tuple
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen


def inject_github_token(url: str, token: str) -> str:
    """https://github.com/a/b.git → https://git:TOKEN@github.com/a/b.git"""
    token = (token or "").strip()
    if not token or "github.com" not in url:
        return url
    parsed = urlparse(url)
    if parsed.hostname != "github.com":
        return url
    # x-access-token działa z PAT (classic i fine-grained)
    netloc = f"x-access-token:{token}@github.com"
    if parsed.port:
        netloc += f":{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


def github_zip_url(url: str) -> Optional[str]:
    """Z adresu repozytorium GitHub buduje URL archiwum ZIP (gałąź main, potem master)."""
    parsed = urlparse(url)
    if parsed.hostname not in ("github.com", "www.github.com"):
        return None
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    return f"https://github.com/{owner}/{repo}/archive/refs/heads/main.zip"


def _run_git(args: list, cwd: str | None = None) -> Tuple[int, str]:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = "echo"
    try:
        proc = subprocess.run(
            args, cwd=cwd, env=env, capture_output=True, text=True, timeout=300,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode, out.strip()
    except FileNotFoundError:
        return 127, "Nie znaleziono programu git."
    except subprocess.TimeoutExpired:
        return 124, "Przekroczono czas oczekiwania na git."


def clone_git(url: str, dest: str, token: str = "") -> str:
    """Klonuje repozytorium do dest. Zwraca komunikat błędu albo pusty string."""
    cloned = inject_github_token(url, token)
    code, log = _run_git(["git", "clone", "--depth", "1", cloned, dest])
    if code == 0:
        return ""
    return log or f"git clone zakończył się kodem {code}"


def download_github_zip(url: str, dest: str, token: str = "") -> str:
    """Pobiera ZIP z GitHuba (gdy nie ma gita). Zwraca błąd albo ''."""
    zip_url = github_zip_url(url)
    if not zip_url:
        return "To nie jest adres repozytorium GitHub — potrzebny jest git."
    headers = {"User-Agent": "SuperCAT"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    last_error = ""
    for zip_url in (
        zip_url,
        zip_url.replace("/main.zip", "/master.zip"),
    ):
        try:
            req = Request(zip_url, headers=headers)
            with urlopen(req, timeout=120) as resp:
                data = resp.read()
            tmp = tempfile.mkdtemp(prefix="sc-zip-")
            zpath = os.path.join(tmp, "repo.zip")
            with open(zpath, "wb") as fh:
                fh.write(data)
            with zipfile.ZipFile(zpath) as zf:
                zf.extractall(tmp)
            # GitHub pakuje do folderu repo-branch/
            inner = None
            for name in os.listdir(tmp):
                full = os.path.join(tmp, name)
                if os.path.isdir(full) and name != "__MACOSX":
                    inner = full
                    break
            if inner is None:
                last_error = "Puste archiwum ZIP."
                continue
            os.makedirs(dest, exist_ok=True)
            for item in os.listdir(inner):
                src = os.path.join(inner, item)
                dst = os.path.join(dest, item)
                if os.path.exists(dst):
                    continue
                shutil.move(src, dst)
            shutil.rmtree(tmp, ignore_errors=True)
            return ""
        except Exception as exc:
            last_error = str(exc)
            continue
    return last_error or "Nie udało się pobrać archiwum."


def fetch_remote_project(url: str, dest_parent: str, token: str = "") -> Tuple[str, str]:
    """Pobiera projekt. Zwraca (ścieżka_folderu, błąd)."""
    url = (url or "").strip()
    if not url:
        return "", "Podaj adres URL (GitHub / git)."
    dest_parent = os.path.abspath(dest_parent or os.path.expanduser("~/SuperCAT_Projects"))
    os.makedirs(dest_parent, exist_ok=True)
    name = _folder_name_from_url(url)
    dest = os.path.join(dest_parent, name)
    if os.path.exists(dest) and os.listdir(dest):
        return dest, ""  # już jest — otwórz
    git = shutil.which("git")
    if git:
        err = clone_git(url, dest, token)
        if not err:
            return dest, ""
        # spróbuj ZIP, gdy git nie dał rady (brak repo / zły token)
        zip_err = download_github_zip(url, dest, token)
        if not zip_err:
            return dest, ""
        return "", err or zip_err
    err = download_github_zip(url, dest, token)
    if err:
        return "", err + "\n(Zainstaluj git, żeby klonować dowolne repozytoria.)"
    return dest, ""


def _folder_name_from_url(url: str) -> str:
    path = urlparse(url).path.strip("/")
    if not path:
        return "projekt_z_sieci"
    name = path.split("/")[-1]
    if name.endswith(".git"):
        name = name[:-4]
    name = re.sub(r"[^\w.\-]+", "_", name) or "projekt_z_sieci"
    return name


def find_or_create_scproj(folder: str, source_lang: str = "en",
                          target_lang: str = "pl") -> str:
    """Znajduje .scproj w folderze albo tworzy nowy projekt SuperCAT w tym miejscu."""
    folder = os.path.abspath(folder)
    for root, _dirs, files in os.walk(folder):
        # nie grzeb w .git
        if os.path.basename(root) == ".git":
            continue
        for name in files:
            if name.endswith(".scproj"):
                return os.path.join(root, name)
        # tylko pierwszy poziom + jeden w dół
        if root != folder and os.path.dirname(root) != folder:
            break

    from .project import PROJECT_FOLDERS, Project, ProjectManager

    name = os.path.basename(folder.rstrip(os.sep)) or "Projekt z sieci"
    # OmegaT: source/ już bywa w repo
    for sub in PROJECT_FOLDERS:
        os.makedirs(os.path.join(folder, sub), exist_ok=True)
    project = Project(
        name=name,
        source_lang=source_lang,
        target_lang=target_lang,
        project_path=folder,
    )
    mgr = ProjectManager.instance()
    mgr.current = project
    mgr.save_project()
    return project.project_file_path
