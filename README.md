# SuperCAT Workbench

Narzędzie CAT (Computer-Aided Translation) w Pythonie — **wszystkie funkcje z repozytorium
[danerx77/5](https://github.com/danerx77/5)** (oryginalnie Java + Swing) przepisane na Pythona,
w interfejsie wzorowanym na
[Supervertaler-Workbench](https://github.com/Supervertaler/Supervertaler-Workbench):
jedno okno, górny pasek narzędzi i zakładki zamiast wielu okien.

## Ikona / EXE

Ikona aplikacji: `supercat/assets/supercat.ico` (16–256 px, motyw „A → Ł”) —
ładowana automatycznie do okna **i paska zadań** (nie zostawia domyślnej
ikony Pythona). Przy budowie EXE (PyInstaller):

```
pyinstaller --onefile --windowed --name SuperCAT --icon supercat/assets/supercat.ico SuperCAT.py
```

## Uruchomienie

```bash
pip install -r requirements.txt
python SuperCAT.py
```

Wymagania: Python 3.10+ oraz PyQt6, python-docx, openpyxl.

## Interfejs

Jedno okno, siedem zakładek (jak w Supervertaler Workbench):

| Zakładka | Zawartość |
|---|---|
| 🤖 **AI** | dziennik pracy modelu, podgląd polecenia, wytyczne, test tłumaczenia |
| 📝 **Edytor** | lista plików **z licznikiem postępu na bieżąco** (`plik.txt (91/1000 • 9%)`, ✅ przy ukończonych) **+ własne znaczniki plików** (✓ sprawdzone / ⚠️ uwaga / ✗ problem, klik prawym) • siatka segmentów • edytor źródło/cel • **panele po prawej: wybór układu** (wszystko naraz / **zakładki pionowe, po lewej**) **+ wybór, które panele się pokazują** **+ regulacja czcionki** • **szerokości kolumn zapamiętywane** i **widoczne uchwyty** do przeciągania • **kolumny siatki przesuwne myszą** (sąsiad ustępuje miejsca, prawy przycisk na nagłówku = dopasowanie/reset) |
| 💾 **Pamięć TM** | **Lista pamięci** (baza projektu, pliki TMX z folderu `tm/` oraz pamięci zaimportowane z innych lokalizacji) oraz **Przeglądaj i edytuj** – edycja wpisów dwuklikiem bezpośrednio w tabeli, import/eksport TMX |
| 🏷️ **Glosariusz** | termbaza projektu, import/eksport CSV |
| 📖 **Słowniki** | słowniki Hunspell/txt, sprawdzanie pisowni |
| 🔍 **Znajdź i zamień** | wyszukiwanie w **całym projekcie albo w wybranych plikach**, wyniki pogrupowane po plikach, ignorowanie znaczników i ogonków, podświetlanie trafień w edytorze, zamiana w zaznaczonych wynikach |
| ✅ **QA i statystyki** | kontrola jakości + statystyki projektu, eksport raportu |
| ⚙️ **Ustawienia** | ogólne, pamięć TM, tłumaczenie maszynowe, segmentacja |

## Funkcje przeniesione z repozytorium `danerx77/5`

| Klasa Java (repo `5`) | Odpowiednik w Pythonie |
|---|---|
| `Main.java`, `gui/MainWindow.java` | `supercat/app.py`, `supercat/ui/main_window.py` |
| `models/Project.java` | `supercat/core/project.py` |
| `config/SettingsManager.java` | `supercat/core/settings.py` |
| `services/ProjectManager`, `RecentProjectsManager` | `core/project.py` (`ProjectManager`, `RecentProjects`) |
| `services/SegmentationService` | `core/segmentation.py` |
| `services/TranslationMemoryService` | `core/tm.py` |
| `services/TagProtectionService` | `core/tags.py` |
| `services/FileParserService` | `core/fileparser.py` |
| `services/GlossaryService`, `DictionaryService`, `SpellCheckerService` | `core/glossary.py` |
| `services/MachineTranslationService` | `core/mt.py` |
| `services/StatisticsService`, `dialogs/QADialog` | `core/qa.py`, `ui/qa_tab.py` |
| `panels/EditorPanel`, `FuzzyMatchesPanel`, `FilesPanel` | `ui/editor_tab.py` (scalone w jeden widok) |
| `panels/SentenceMatchingPanel` + `findSentenceMatches` | `core/tm.py` (`find_sentence_matches`) + zakładka „🔗 Dopasowanie zdań” |
| `panels/TMPanel`, `GlossaryPanel`, `DictionaryPanel`, `SearchPanel` | `ui/tm_tab.py`, `ui/glossary_tab.py`, `ui/search_tab.py` |
| `dialogs/NewProjectDialog`, `ProjectSettingsDialog`, `SegmentationPreviewDialog`, `AboutDialog` | `ui/dialogs/project_dialogs.py` |
| `dialogs/SettingsDialog` | `ui/settings_tab.py` (jako zakładka, nie okno modalne) |

### Szczegółowo

**Projekty** — struktura folderów `source/ target/ tm/ glossary/ dictionary/ export/`,
plik projektu `.scproj` (JSON), lista ostatnio otwieranych, README w katalogu projektu.

**Menu podręczne listy plików** (prawy przycisk myszy) — operacje na **pojedynczym pliku**
zamiast na całym projekcie:

* 💡 **Zastosuj TM** tylko do tego pliku,
* 🤖 **Przetłumacz maszynowo** tylko ten plik,
* 👁️ pokaż wyłącznie jego segmenty,
* 📊 statystyki pliku,
* ➕ dodaj pliki,
* 🗑️ **usuń plik z projektu** — kasuje go z folderu `source/`, usuwa jego segmenty
  i zapisane tłumaczenia. Przed usunięciem program ostrzega, ile segmentów ma już
  tłumaczenie, żeby nie stracić pracy przez pomyłkę.

**Nawigacja klawiaturą** — segmenty przełącza się strzałkami z modyfikatorem: `Ctrl+↑/↓`,
`Alt+↑/↓` lub `Ctrl+PgUp/PgDn`, a `Ctrl+Home`/`Ctrl+End` skaczą na początek i koniec.
Działa **także w trakcie pisania** w polu tłumaczenia — same strzałki (bez modyfikatora)
nadal przesuwają kursor w tekście, więc nic nie koliduje. W siatce segmentów wystarczą zwykłe
strzałki. Pozycja w menu *Edycja → Nawigacja po segmentach*.

**Import plików** — TXT, DOCX, XLSX, XLIFF/XLF, PO/POT, SRT, HTML/HTM, MD, CSV, XML.
Pliki można **przeciągnąć myszą** (drag & drop) na listę plików projektu albo w dowolne miejsce
okna — panel podświetla się przerywaną ramką, gdy upuszczenie zadziała. Można też upuścić cały
**folder**: program weźmie z niego obsługiwane pliki, a resztę pominie z informacją, co odrzucił.
Przy nadpisywaniu pliku o tej samej nazwie program pyta o potwierdzenie.

**Segmentacja** — tryby: zdania (z obsługą skrótów typu „np.”, „itd.” i liczb dziesiętnych),
wiersze, akapity, własny separator, wyrażenie regularne. Dostępny podgląd segmentacji.

**Pamięć tłumaczeń** — baza SQLite w projekcie, dopasowania rozmyte z progiem procentowym,
automatyczne wstawianie najlepszego dopasowania, konkordancja, import/eksport TMX 1.4,
automatyczny import wszystkich plików `.tmx` z folderu `tm/` przy otwarciu projektu.

> ⚠️ **Dopasowanie zdań jest domyślnie WYŁĄCZONE.** Przy dużych pamięciach potrafi
> spowalniać program. Włącz je w *Ustawieniach → Pamięć TM → Dopasowanie zdań*.

**Dopasowanie zdań** — gdy segment jest dłuższy niż wpisy w TM, program szuka w pamięci
fragmentów zawartych w segmencie i podstawia ich tłumaczenia. Dodatkowo składa propozycję
zbiorczą ze **wszystkich** niezachodzących na siebie fragmentów naraz (w oryginale Java każdy
fragment dawał osobną sugestię). Wyniki są posortowane po pokryciu segmentu.

**Rozbicie wpisu TM na linie** — wpis pamięci obejmujący kilka wyświetlanych linii jest
dzielony po `\n` / `\p` i pokazywany linia po linii, np.:

```
Thank you for using the MYSTERY   →  Dziękujemy za korzystanie z
GIFT System.                      →  Systemu MYSTERY GIFT
```

Pod spodem widać złożoną całość gotową do wstawienia. Wyniki oznaczone są typem:
`linia` (rozbicie po znacznikach), `fragment` (część segmentu) lub `złożenie` (kilka fragmentów).

**Odrzucanie wpisów nieprzetłumaczonych** — wpisy, w których tłumaczenie jest kopią źródła
(np. `System.` → `System.`), nie trafiają już do podpowiedzi jako bezużyteczne
„dopasowanie 100%". Dotyczy to również wpisów jedno- i dwuwyrazowych, wcześniej pomijanych
przez filtr.

**Złożenie zawiera cały segment** — propozycja to oryginalny tekst z podstawionym fragmentem
(z zachowaniem `\n`, `\p` i zmiennych typu `{STR_VAR_1}`), a nie samo tłumaczenie jednej linii.
Pokrycie liczone jest względem długości całego segmentu.

**Wymóg pokrycia słów** — wpis z pamięci musi pokryć co najmniej 60% słów linii segmentu.
Bez tego jednowyrazowy wpis (np. „System") uchodził za dopasowanie całej linii
(„GIFT System.") w 90% i wypierał sensowne podpowiedzi. Sama proporcja długości tu nie
wystarcza – rozstrzyga dopiero pokrycie słów.

**Porównywanie całych zdań, nie urwanych linii** — dopasowanie zdań scala linie przełamane
znacznikiem, zanim porówna je z pamięcią. Wcześniej porównywało urwane kawałki
(`Thank you for using the STAMP CARD` i osobno `System.`), przez co sensowne wpisy przepadały,
a w wynikach lądowały bezużyteczne dopasowania typu „System. → System.".

Cache pamięci zawiera teraz **zarówno całe wpisy, jak i pojedyncze linie**, więc pełne zdanie
segmentu paruje się z pełnym tłumaczeniem. Wynik pokazuje rozbicie linia po linii, a „całość"
to cały segment z podstawionym fragmentem — nawet gdy zdanie w oryginale jest przełamane
znacznikiem (podstawienie działa po treści, z pominięciem `\n` i `\p`).

**Rozmyte dopasowanie linii** — najważniejszy tryb w praktyce. Wpis w pamięci rzadko jest
dokładną kopią fragmentu segmentu: bywa inne słowo (`accessing` zamiast `using`) albo dodatkowy
znacznik (`<<KON>>`). Dlatego każda linia segmentu jest porównywana **rozmyto** z liniami
wpisów TM, a podpowiedź pokazuje najlepiej pasującą. Próg ustawia się w Ustawieniach → Pamięć TM.

**Podpowiedzi z bieżącej sesji** — segmenty przetłumaczone w projekcie są od razu widoczne
w podpowiedziach i w dopasowaniu zdań, jeszcze zanim trafią do bazy TM (opcja
„Podpowiadaj z segmentów przetłumaczonych w projekcie”).

**Segment krótszy niż wpis TM** — gdy segmentacja rozbiła zdanie po `\n`, a pamięć trzyma
całość, program rozpoznaje relację odwrotną i pokazuje tę linię wpisu, która odpowiada
segmentowi (np. dla segmentu `GIFT System.` podpowie `Systemu MYSTERY GIFT`).

**Tłumaczenie linia po linii** — silniki MT przestawiają znaczniki końca wiersza (MyMemory
potrafi przenieść `\n` na koniec zdania). Dlatego każda linia jest tłumaczona osobno, a `\n`
i `\p` zostają dokładnie tam, gdzie były. Opcję można wyłączyć w Ustawieniach → MT.

**Ochrona znaczników w tłumaczeniu maszynowym** — przed wysłaniem do silnika znaczniki
(`\n`, `\p`, `{PLAYER}`, `<b>`) są zastępowane neutralnymi tokenami i przywracane po
tłumaczeniu. Bez tego MyMemory i Google zwracały uszkodzone `\ n` albo gubiły znaczniki.
Usuwane są też spacje, które silniki dostawiają wokół znaczników.

**📝 Edytor pamięci TM / TMX** (`Ctrl+Shift+X`, także Narzędzia i zakładka Pamięć TM) —
odpowiednik TMX Editora z Supervertaler Workbench: siatka dwujęzyczna ze stronicowaniem,
panel edycji nad siatką, filtrowanie (w tym „tylko problematyczne”), dodawanie i usuwanie
jednostek, kopiowanie źródła do celu, znajdź i zamień w całej pamięci (z regex),
usuwanie duplikatów i pustych wpisów, przycinanie spacji, czyszczenie znaczników,
statystyki oraz otwieranie i zapisywanie plików TMX.

**Znaczniki `\n`, `\p` (pliki gier, napisy, zasoby)** — ta sama treść bywa zapisana raz jako
literalne `\n` (backslash + litera), a raz jako prawdziwy przełam wiersza. Przy porównaniach
wszystkie warianty są sprowadzane do wspólnej postaci, więc wpis TM
`Thank you for using the MYSTERY\nGIFT System.` zostaje rozpoznany w segmencie niezależnie od
sposobu zapisu i rozmieszczenia znaczników. Podmiana zachodzi na oryginale, więc pozostałe
znaczniki (`\p`, `{PLAYER}`) zostają nienaruszone.

**Adaptacja tagów** — tagi z aktualnego segmentu źródłowego (`{ZMIENNA}`, `<b>`, `[x]`, `\n`,
`<<KON>>`) są podstawiane do podpowiedzi z TM; przy porównywaniu podobieństwa tagi są
normalizowane, żeby różna długość nazw zmiennych nie zaniżała procentu dopasowania.

**Glosariusz i słowniki** — termbaza CSV z podświetlaniem terminów w tekście źródłowym,
dodawanie terminu z zaznaczenia, import/eksport; słowniki `.dic`/`.txt` i sprawdzanie pisowni.

**🤖 Zakładka AI** — uproszczony odpowiednik sekcji AI z Supervertaler Workbench, ograniczony
do tego, co potrzebne przy tłumaczeniu (bez czatu i menedżera promptów):

* **Dziennik pracy** — na żywo widać, co program robi (wysyłanie, oczekiwanie, odpowiedź, czas),
  więc podczas długiej odpowiedzi modelu nie wygląda na zawieszony. Po 15 sekundach dopisuje
  „Nadal czekam na odpowiedź modelu…". Dziennik można skopiować jednym kliknięciem.
* **Wskaźnik bieżącej pracy** — nazwa operacji, licznik czasu i pasek aktywności.
* **Zmienne i podgląd polecenia** — dokładnie to, co trafia do modelu, wraz z terminologią
  z glosariusza i własnymi wytycznymi użytkownika (np. „styl gry retro").
* **Test tłumaczenia** — szybkie sprawdzenie wybranego silnika na próbce lub bieżącym segmencie.

**Znacznik `\n` nie kończy zdania** — w plikach gier przełamanie wiersza często wypada
w środku wyrażenia: `the STAMP CARD\nSystem.` to **jedna nazwa** („STAMP CARD System"),
a nie dwa zdania. Wcześniej program tłumaczył kawałki osobno i wychodziło
`KARTY ZNACZNIKÓW\nSystem.` — „System" jako samodzielne zdanie.

Teraz proste silniki dostają **całe zdania** (fragmenty są scalane aż do kropki), a znaczniki
z wnętrza zdania wracają na swoje miejsce po przetłumaczeniu. Modele AI mają to wyjaśnione
wprost w poleceniu, wraz z przykładem. Efekt na żywym API:

| Silnik | Przed | Po |
|---|---|---|
| Google | `...KARTY ZNACZNIKÓW\nSystem.` | `...z\nSystemu KART ZNACZKOWYCH.` |
| MyMemory | `...KARTY POCZTOWEJ\nSłonecznego.` | `...z\nsystemu KART STEMPLOWYCH.` |

**Cały segment w jednym zapytaniu do AI** — proste silniki (Google, MyMemory) dostają tekst
pocięty po `\n` i `\p`, bo inaczej przestawiają znaczniki. Modele AI są z tego **wyłączone**:
dzielenie odbierało im kontekst i fragment `System.` bez reszty zdania dawał przypadkowe
tłumaczenia oraz warianty typu „X or Y”. AI widzi teraz całe zdanie, a znaczniki chroni
mechanizm symboli zastępczych `@#0#@`.

**Kontrola znaczników po tłumaczeniu** — jeśli model mimo wszystko zgubi `\n`, `\p` lub
`{ZMIENNA}`, program dopisuje brakujące znaczniki (żeby nie zniknęły z pliku) i wpisuje
ostrzeżenie do dziennika AI z informacją, ile ich brakowało.

**🧹 Oczyszczanie odpowiedzi AI** — modele rozumujące (Gemini, Gemma, DeepSeek) potrafią zwrócić
cały tok myślenia zamiast wyniku:

```
* Role: Professional translator (English to Polish).
* "Thank you for using" -> "Dziękujemy za korzystanie z"
* Self-correction: ...
Result: Dziękujemy za korzystanie z MYSTERY
```

Program rozpoznaje takie odpowiedzi i wyciąga **samo tłumaczenie**. Obsługiwane są bloki
`<think>`, znaczniki kodu, etykiety `Result:` / `Final choice:`, listy wariantów i cudzysłowy
obejmujące całość. Usuwane są też **podwojone tłumaczenia** (`Zdanie.Zdanie.`) oraz
**warianty** rozdzielone „or”/„lub” — zostaje pierwsza wersja. Samo polecenie systemowe zostało też przepisane tak, by wyraźnie zabraniać
dopisywania rozumowania.

**🔑 Google Gemini (AI Studio)** — darmowy klucz **bez karty płatniczej**: utwórz go na
[aistudio.google.com/apikey](https://aistudio.google.com/apikey) i wklej w *Ustawienia →
Tłumaczenie maszynowe → Klucz Google Gemini*. Domyślny model to alias **`gemini-flash-latest`**, który zawsze wskazuje aktualną
wersję Flash — nazwy modeli Google zmienia co kilka miesięcy, a starsze (np. `gemini-2.5-flash`)
bywają blokowane dla **nowo utworzonych projektów** komunikatem *„no longer available to new
users"*. Jeśli mimo to trafisz na taki błąd, program **sam pobierze listę modeli dostępnych dla
Twojego klucza, przełączy się na działający i go zapamięta**. Listę można też odświeżyć ręcznie
przyciskiem **„🔄 Pobierz modele"** obok pola modelu. Darmowy plan to ok. **10 zapytań
na minutę i 250 na dobę** — wykorzystanie widać na bieżąco w liczniku zużycia.

**⚡ Licznik zużycia** — w prawym dolnym rogu widnieje wskaźnik bieżącego silnika, np.
`⚡ Google: 7/10 na min • 84/250 dziś • 9 450 tok. (34%)`. Powyżej 80% limitu robi się
pomarańczowy, powyżej 95% czerwony. **Kliknięcie** (albo *Narzędzia → Zużycie silników MT*)
otwiera pełne zestawienie: zapytania, tokeny, znaki i błędy per silnik. Liczniki dobowe zerują
się o północy i **przeżywają restart programu** (zapisywane w `~/.supercat/usage.json`) — inaczej
po ponownym uruchomieniu pokazywałyby zero, mimo że limit u dostawcy nadal jest naliczony.
Nieudane wywołania też są liczone, więc widać, kiedy limit został wyczerpany.

**🤖 Puter AI (Gemma, GPT, Claude)** — dostęp do 500+ modeli przez bramę Puter, w tym
darmowe **Gemma**. Aplikacja korzysta z endpointu zgodnego z OpenAI
(`https://api.puter.com/puterai/openai/v1/`), bo przeglądarkowa biblioteka `puter.js` z
poradnika nie działa w programie desktopowym. **Konfiguracja:** załóż bezpłatne konto na
[puter.com](https://puter.com), skopiuj token z ustawień konta i wklej w
*Ustawienia → Tłumaczenie maszynowe → Token Puter AI*. Model można zmienić (domyślnie
`google/gemma-3-27b-it`). Rozliczenie działa w modelu „User-Pays" — każdy użytkownik korzysta
z limitów własnego konta.

**Tłumaczenie maszynowe** — silniki **bez klucza API**: Google Translate,
**Microsoft Translator (Bing)**, **DeepL przez stronę**, MyMemory, LibreTranslate
(własny serwer) i lokalny słownikowy (offline). Z kluczem: **Azure Translator**, DeepL Pro/Free, OpenAI (oraz API zgodne),
Google Gemini, Puter AI, IBM Watson, własny endpoint HTTP. Klucze w
`~/.supercat/api_keys.json`. Tłumaczenie pojedynczego segmentu, całego projektu
(Narzędzia → „Tłumacz wszystko darmowymi silnikami”) lub porównanie kilku silników naraz.

**Wybór silnika** — w Ustawieniach → Tłumaczenie maszynowe można osobno wskazać silnik dla
pojedynczego segmentu (`Ctrl+M`) i **silnik operacji zbiorczych** („Tłumacz wszystko”,
automatyka po wczytaniu), a także **zaznaczyć, które silniki porównuje QuickTrans**.
Ten sam silnik zmienisz **bez wchodzenia w ustawienia** — listą nad polem tłumaczenia
w Edytorze.

### 🤖 Szybki wybór tłumacza w Edytorze

Tuż nad polem tłumaczenia jest pasek **🤖 Silnik MT** z listą wszystkich silników,
przełącznikiem *tylko bez klucza* oraz przyciskami **🤖 Tłumacz** (`Ctrl+M`)
i **⚡ Porównaj** (QuickTrans). Gdy Google odmówi albo wynik brzmi źle, wystarczy wybrać
inny silnik z listy i kliknąć „Tłumacz” — bez przechodzenia do zakładki Ustawienia.

* Silniki, do których brakuje klucza, są oznaczone **🔑** — od razu widać, co zadziała.
* Wybór jest **wspólny** z Ustawieniami: zmiana w jednym miejscu przestawia drugie.
* Przełącznik *tylko bez klucza* skraca listę do pięciu silników działających od ręki
  (zapamiętywany między uruchomieniami).

### ⚡ Które silniki porównuje QuickTrans

*Ustawienia → 🤖 Tłumaczenie maszynowe → **⚡ QuickTrans — które silniki porównywać***
to lista wszystkich silników z polami wyboru. Zaznaczone są odpytywane równolegle.
Gdy **nic nie zaznaczysz**, działa tryb automatyczny: program bierze wszystkie gotowe silniki,
z uwzględnieniem przełącznika „pytaj tylko silniki bez klucza API”. Przyciski
**Zaznacz darmowe** i **Wyczyść (automatycznie)** ustawiają listę jednym kliknięciem,
a etykieta obok pokazuje bieżący stan („Wybrano 3 silników” / „Tryb automatyczny”).
Silnik zaznaczony, ale nieskonfigurowany (brak klucza), jest pomijany — QuickTrans nie
marnuje czasu na zapytania, które i tak zwrócą błąd.

**Automatyka po wczytaniu tekstu** — Ustawienia → Pamięć TM → „Po wczytaniu tekstu”: po
imporcie plików lub otwarciu projektu program może sam uzupełnić tłumaczenia z pamięci TM
(z konfigurowalnym progiem dopasowania), a następnie opcjonalnie przetłumaczyć maszynowo
segmenty, których TM nie pokryła. Można też wyłączyć pytanie o potwierdzenie.

**⚡ QuickTrans** (`Ctrl+Shift+Q`) — odpowiednik QuickTrans z Supervertaler Workbench: jedno okno
odpytuje **równolegle wybrane silniki** (domyślnie wszystkie dostępne) i pokazuje ich propozycje
z kolorowym kodem dostawcy. Wybór klawiszem 1–9 lub podwójnym kliknięciem, tekst źródłowy można
edytować i tłumaczyć ponownie, przełącznik „tylko silniki bez klucza API”, a listę silników
ustawia się w Ustawieniach (patrz wyżej).

**QA** — puste segmenty, niezgodność liczb, niezgodność tagów, proporcja długości,
interpunkcja, wielkość liter, tekst identyczny ze źródłem, podwójne spacje, nieużyte terminy
glosariusza, pisownia, spójność tłumaczeń. Raport do pliku tekstowego.

**Eksport** — odtworzenie oryginału z podmienionym tekstem do `target/` (DOCX i XLSX
z zachowaniem układu dokumentu), a także XLIFF, PO, SRT, TMX, HTML dwujęzyczny, TXT.

## Słowniki — pobieranie i dodawanie w programie

Zakładka **📖 Słowniki** pozwala zarządzać słownikami bez grzebania w katalogach:

| Przycisk | Działanie |
|---|---|
| **📂 Otwórz folder słowników** | otwiera katalog `<projekt>/dictionary/` w menedżerze plików systemu; obok widnieje pełna ścieżka do skopiowania |
| **➕ Dodaj słownik z pliku…** | kopiuje wybrany plik `.dic` (Hunspell) lub `.txt` (lista słów) do projektu — można wskazać kilka naraz |
| **⬇ Pobierz słownik…** | pobiera gotowy słownik wprost z repozytorium LibreOffice, z paskiem postępu i w tle |
| **🗑️ Usuń zaznaczony** | usuwa plik słownika z projektu |
| **🔄 Przeładuj** | wczytuje ponownie zawartość folderu |

### Który słownik wybrać

| Słownik | Zawiera | Kiedy używać |
|---|---|---|
| **polski – pełna odmiana, 4,5 mln form (SJP.pl)** ★ | wszystkie formy odmienione wypisane wprost | **zalecany** — działa zawsze, także bez `spylls` |
| polski `pl_PL.dic` (LibreOffice) | tylko formy podstawowe + reguły w `.aff` | gdy masz zainstalowany `spylls` |

**Dlaczego to ważne.** Plik `.dic` zawiera wyłącznie formy podstawowe — nie ma w nim
`Witamy`, `Dziękujemy` ani `Systemu`, bo te powstają dopiero z reguł `.aff`. Bez silnika
Hunspell połowa poprawnych wyrazów byłaby podkreślana. Lista SJP.pl (12 MB spakowane,
rozpakowywana automatycznie) ma **4 543 182 formy** wypisane wprost, więc problem znika.
Adres pobierania zmienia się z każdą aktualizacją SJP — program sam znajduje aktualny.

Pozostałe do pobrania: angielski (US/GB), niemiecki, hiszpański, włoski, czeski, rosyjski,
ukraiński. Lista pokazuje każdy plik z liczbą słów i wykrytym kodowaniem, a nagłówek
informuje, czy działa pełna odmiana.

**Kodowanie i odmiana.** Słowniki Hunspell nie są w UTF-8 — polski `pl_PL.dic` jest zapisany
w **ISO-8859-2**. Program czyta deklarację `SET` z pliku `.aff`, a gdy go brak, rozpoznaje
kodowanie z treści. Bez tego zamiast `oknówka` pojawiało się `okn�wka`.
Plik `.dic` zawiera przy tym wyłącznie **formy podstawowe** — `dziękujemy` czy `systemu`
powstają dopiero z reguł `.aff`. Dlatego program używa silnika **Hunspell (`spylls`)**,
który rozumie odmianę; pobierając słownik, ściąga `.aff` automatycznie. Nagłówek zakładki
pokazuje, czy działa pełna odmiana, czy tylko lista wyrazów.

## Kontrola poprawności języka (tylko tłumaczenie)

Program sprawdza **wyłącznie tekst tłumaczenia** — nigdy źródła. Dwa poziomy:

**1. Reguły wbudowane (bez internetu, ~0,14 ms na segment)**

* interpunkcja: spacja przed przecinkiem, brak spacji po nim, powtórzone znaki,
  niesparowane nawiasy i cudzysłowy,
* **odmiana**: rzeczownik po liczebniku (`pięć jabłko` → dopełniacz), zgodność
  zaimka z czasownikiem (`ja poszedł`), mianownik po `dwa/trzy/cztery`,
* powtórzony wyraz (`to to jest`), mała litera po kropce (ze znajomością skrótów `np.`, `itd.`),
* typowe błędy: `wziąść`, `włanczać`, `poszłem`, `na prawdę`, `tą książkę`, pleonazmy,
* pisownia na podstawie wczytanych słowników (dopiero od 5 000 słów, żeby nie zalewać szumem).

**2. LanguageTool — pełna gramatyka**

W *Ustawienia → 🔤 Pisownia i język* są **dwie osobne sekcje**, każda z własnym
wyłącznikiem i własnym przyciskiem sprawdzania. Włączenie jednej wyłącza drugą.

**💻 LanguageTool offline — silnik na tym komputerze**

| Element | Działanie |
|---|---|
| ☑ **Włącz sprawdzanie offline** | własny wyłącznik trybu lokalnego |
| **⬇ Pobierz silnik offline (~230 MB)** | jednorazowe pobranie; przycisk gaśnie, gdy silnik już jest |
| **🔌 Sprawdź silnik offline** | uruchamia i potwierdza działanie |
| **🗑️ Usuń silnik z dysku** | zwalnia miejsce (~500 MB po rozpakowaniu) |

Pasek stanu mówi wprost, co się dzieje: *„✅ Silnik pobrany (372 MB) — sprawdzanie działa
bez internetu”* albo *„ℹ️ Silnik nie jest jeszcze pobrany”*.

**Pobieranie pokazuje rzeczywisty postęp w procentach** — pasek wypełnia się od 0 % do 100 %
wraz z licznikiem megabajtów: `Pobieranie silnika: 42%   (92,4 / 220,3 MB)`.
Biblioteka `language-tool-python` raportuje postęp przez `tqdm` w konsoli, więc SuperCAT
podstawia własny licznik i przekazuje dane wprost do paska. Transfer idzie **w tle**
(okno pozostaje responsywne), a po zakończeniu tryb offline włącza się sam.
Zalety: tekst **nie opuszcza komputera**, brak limitu zapytań, sprawdzenie zdania ~100 ms.

**Wykrywanie Javy.** Biblioteka `language-tool-python` szuka Javy wyłącznie w `PATH`, więc
gdy siedzi tam stara wersja (np. 1.8), nowszy JDK jest ignorowany — nawet jeśli masz
zainstalowaną Javę 26. SuperCAT przeszukuje dodatkowo `JAVA_HOME` oraz typowe katalogi
instalacyjne (Program Files\Java, Eclipse Adoptium, Microsoft JDK, Corretto, Zulu, JetBrains,
`/usr/lib/jvm`, `/Library/Java/…`) i **wybiera najnowszą znalezioną**, ustawiając dla niej
`PATH` i `JAVA_HOME` przed startem silnika.

Wersja silnika jest dobierana automatycznie do posiadanej Javy:

| Java | Wersja LanguageTool |
|---|---|
| 17 i nowsza | najnowsza (6.x) |
| 9 – 16 | 5.9 |
| 8 i starsza | brak zgodnej — potrzebna aktualizacja Javy |

Zakładka pokazuje wykrytą wersję i ścieżkę, a pole **Własna ścieżka** (z przyciskami
**📂 Wskaż…** i **🔄 Wykryj ponownie**) pozwala wskazać konkretny plik `java`, gdyby
automat wybrał nie tę instalację, o którą chodziło.

**🌐 LanguageTool online — serwer w internecie**

| Element | Działanie |
|---|---|
| ☑ **Włącz sprawdzanie przez internet** | osobny wyłącznik trybu sieciowego |
| **Serwer** | puste = publiczne `api.languagetool.org` (limit ~20 zapytań/min), albo własny adres, np. `http://localhost:8081/v2/check` |
| **🔌 Sprawdź połączenie z serwerem** | osobny test, niezależny od trybu offline |

**Błędy są podkreślane wprost w polu tłumaczenia — jak w edytorze tekstu:**
literówka i błąd dostają **czerwoną falkę**, ostrzeżenie pomarańczową, drobna uwaga
niebieską kropkowaną. **Prawy przycisk myszy** na podkreślonym wyrazie pokazuje
**propozycje poprawnego wyrazu** (kliknięcie podmienia go w tekście) oraz opcję
**➕ Dodaj do słownika** (zapis do `uzytkownika.txt` w projekcie). Panel **🔤 Język** obok
wypisuje wszystkie uwagi: dwuklik wstawia poprawkę, a **✨ Popraw automatycznie** stosuje
wszystkie jednoznaczne propozycje. Sprawdzanie działa w tle (`Ctrl+Shift+J` wymusza je od razu).

**Szybkość.** Hunspell liczy propozycje ok. 3 s na wyraz, więc dla kilku literówek panel
czekałby kilkanaście sekund. Dlatego podkreślenia i propozycje są rozdzielone:

| Etap | Czas |
|---|---:|
| podkreślenie błędów (to widzisz od razu) | **14 ms** |
| podpowiedź wyrazu z listy 4,5 mln form | **0,05 s** (indeks litera+długość) |
| szybkie propozycje (dopasowanie po formach podstawowych) | ~0,1 s / wyraz |
| dokładne propozycje Hunspella (dochodzą w tle) | ~3 s / wyraz |

Wcześniej całość liczyła się przed pokazaniem czegokolwiek — **4,83 s** na segment.
Kontrola trafia też do zakładki **✅ QA** jako kategorie `Język: …` dla całego projektu.

Gdy słownika brak, panel **mówi o tym wprost** („⚠️ brak słownika – pisownia NIE jest
sprawdzana”) zamiast wyświetlać mylące „nie znaleziono uwag”. Wyrazy pisane WERSALIKAMI
(`MYSTERY`, `GIFT`) są pomijane — w grach to nazwy własne, których nie ma w słownikach.

### Wszystkie przełączniki w jednym miejscu

Zakładka *Ustawienia → **🔤 Pisownia i język*** zbiera wszystkie opcje:

| Grupa | Przełączniki |
|---|---|
| **Główny wyłącznik** | „Włącz kontrolę poprawności języka” — wyłączony gasi całość i wyszarza resztę |
| **Co sprawdzać** | na bieżąco • podkreślanie w polu • pisownia • odmiana i gramatyka • interpunkcja i powtórzenia • pomijanie WERSALIKÓW |
| **💻 LanguageTool offline** | włącznik • pobieranie silnika • test • usuwanie z dysku • wykryta Java i wybór własnej ścieżki |
| **🌐 LanguageTool online** | włącznik • adres serwera • własny test połączenia |
| **Inne miejsca** | uwagi w QA • porządkowanie wyniku MT • reguły odmiany dla AI |

Na dole **✅ Włącz wszystko** / **🚫 Wyłącz wszystko** przestawia komplet jednym kliknięciem.

**Znaczniki gier są pomijane** — `\n`, `\p`, `<<KON>>`, `{STR_VAR_1}` nie są zgłaszane jako
błędy pisowni. Maskowanie zachowuje długość tekstu, więc podkreślenia LanguageTool
wskazują właściwe miejsce.

## Jakość tłumaczenia maszynowego i AI

**Silniki AI** (Gemini, OpenAI, Puter) dostają w poleceniu osobny blok wymagań:
naturalny styl bez kalek, poprawna **odmiana** (przypadki, liczba, rodzaj, osoba),
uzgodnienie przymiotników z rzeczownikiem, poprawny szyk i interpunkcja, jednolita
forma zwracania się do odbiorcy oraz budowanie zdań tak, by po podstawieniu zmiennych
(`{PLAYER}`, `{STR_VAR_1}`) tekst pozostał gramatyczny. Można to wyłączyć:
*Ustawienia → Tłumaczenie maszynowe → „AI: wymagaj poprawnej odmiany i naturalnego stylu”*.

**Zwykłe silniki** (Google, MyMemory) nie rozumieją poleceń, więc ich wynik jest
automatycznie porządkowany: spacja przed przecinkiem, brak spacji po nim, podwójne spacje,
odstępy przy nawiasach i cudzysłowach, wielka litera na początku zdania. To poprawki
**mechaniczne** — nie zmieniają doboru słów, a liczba znaczników jest pilnowana, więc nie
mogą zepsuć pliku gry. Przełącznik: *„Popraw interpunkcję i spacje w wyniku tłumaczenia”*.

## Segmentacja — reguły i podgląd na żywo

Zakładka *Ustawienia → **✂️ Segmentacja*** została przebudowana na wzór OmegaT:

**Tryb** — z opisem zamiast technicznej nazwy: *Zdania (zalecane)*, *Wiersze*, *Akapity*,
*Własny separator*, *Wyrażenie regularne*. Pola nieistotne dla wybranego trybu są wyszarzane.

**Reguły szczegółowe — kiedy NIE dzielić zdania:**

| Reguła | Przykład |
|---|---|
| Dziel tylko przed wielką literą | `wersja 2.0 działa` zostaje jednym segmentem |
| Nie dziel po liczbie z kropką | `w 1999. roku` |
| Dodatkowe skróty (własna lista) | `zał.`, `rys.` — obok wbudowanych `np.`, `itd.`, `dr` |
| Dziel po znacznikach `\n`, `\p`, `<<KON>>` | tryb „wiersz po wierszu” dla plików gier |
| Scalaj segmenty krótsze niż N znaków | eliminuje strzępki typu `A.` |
| Zachowuj spacje na brzegach | wcięcia dialogów |

**Podgląd na żywo** pokazuje numerowaną listę segmentów wraz z licznikiem słów — każda
zmiana reguły przelicza go natychmiast. Przycisk **📄 Wstaw tekst z projektu** pobiera
fragment prawdziwego pliku. Zapis proponuje od razu ponowne podzielenie plików.

## Generator TM z par plików

*Pamięć TM → **🏗️ Generator TM z plików***

Masz ten sam tekst w dwóch plikach — `text_en.txt` po angielsku i `text_pl.txt` po polsku,
wiersz w wiersz? Ta zakładka zamieni je w gotową pamięć tłumaczeń.

**Jak to działa**

1. **Przeciągnij pliki albo cały katalog** na tabelę (można też „➕ Dodaj pliki”
   / „📁 Dodaj katalog”). Ramka podświetla się na niebiesko, gdy upuszczenie zadziała.
2. Program **paruje pliki automatycznie**. Najpierw po kodzie języka w nazwie
   (`text_en.txt` + `text_pl.txt`, `opis.en.txt` + `opis.pl.txt`, katalogi `en/` i `pl/`),
   a jeśli nazwy nic nie mówią — **po prostu po kolejności**. Dzięki temu `1.txt` + `2.txt`
   działa tak samo dobrze. Nazwa pliku jest **podpowiedzią, nie wymogiem**.
3. **Ustaw język każdej strony** na listach w tabeli — np. `1.txt` = niemiecki,
   `2.txt` = polski. Lista ma 24 języki, a pole jest edytowalne, więc można wpisać
   dowolny kod spoza listy. Podpowiedź z nazwy pliku jest tylko wartością początkową.
4. **Wybierz kodowanie** (kolumna *Kodowanie*): domyślnie „wykryj automatycznie”, ale
   można narzucić UTF-8, Windows-1250, ISO-8859-2, cp1252, cyrylicę, Shift-JIS i inne.
   Po zmianie liczba wierszy przelicza się od razu.
5. Kolumna **Stan** pokazuje, czy para nadaje się do użycia:
   `✅ 6 wierszy` albo `❌ różnica 1 wiersz (2 / 3)`.
6. Zaznacz parę, żeby zobaczyć **podgląd zestawienia** — numer wiersza, źródło i tłumaczenie
   obok siebie. Widać od razu, czy pliki są równoległe.
7. **🏗️ Zbuduj pamięć TM** dopisuje pary do pamięci projektu, a **💾 Zapisz jako TMX**
   eksportuje je do pliku, nie ruszając pamięci.

Przykład: wrzucasz `1.txt` (niemiecki) i `2.txt` (polski), ustawiasz języki na listach
i klikasz „Zbuduj pamięć TM”. W pamięci lądują pary `Guten Tag.` → `Dzień dobry.`
z poprawnie zapisanymi językami `de` / `pl`.

**Dlaczego liczba wierszy musi się zgadzać**

Zestawianie idzie wiersz po wierszu: wiersz N pliku źródłowego łączy się z wierszem N
tłumaczenia. Jeden brakujący wiersz przesuwa **całą resztę pliku** i pamięć staje się
bezużyteczna — dlatego takie pary są domyślnie pomijane, a program mówi wprost, których
plików nie użył i dlaczego. Opcję można wyłączyć („wymagaj zgodnej liczby wierszy”), wtedy
zestawiana jest część wspólna.

**Co jest pomijane** (przełączniki pod tabelą)

| Opcja | Działanie |
|---|---|
| **wiersze techniczne** | `<<< FILE: … >>>`, komentarze `#` i `//`, `[sekcje]`, separatory `---` |
| **identyczne po obu stronach** | wiersz nieprzetłumaczony (np. `OK`) nic nie wnosi do pamięci |
| **nieprzetłumaczone (wciąż po angielsku)** | tłumaczenie zostało w języku źródłowym — patrz niżej |
| **wymagaj zgodnej liczby wierszy** | patrz wyżej — zalecane |
| **min. długość** | pomija bardzo krótkie teksty źródłowe |

### Podgląd pokazuje, co zostanie pominięte i dlaczego

Przełącznik **„pokaż pomijane wiersze”** (nad podglądem, domyślnie włączony) wyświetla
**wszystkie** wiersze pliku, nie tylko te, które wejdą do pamięci. Kolumna **Stan** podaje
powód, więc nie trzeba się domyślać z samych liczników:

| # | Źródło | Tłumaczenie | Stan |
|---|---|---|---|
| 1 | `Hello there.` | `Witaj tam.` | ✅ do TM |
| 2 | | | pusty wiersz |
| 3 | `<<< FILE: city/text.inc >>>` | to samo | wiersz techniczny |
| 4 | `Would you like to save?` | `Czy chcesz zapisać?` | ✅ do TM |
| 5 | `CINNABAR GYM` | `CINNABAR GYM` | identyczne po obu stronach |
| 6 | `Save the game` | `Save the game now` | nieprzetłumaczone (wciąż po angielsku) |

Wiersze wchodzące do pamięci są **zielone**, pomijane **szare**. Wyłączenie przełącznika
zostawia na liście tylko to, co faktycznie trafi do TM.

Puste wiersze i te z tekstem tylko po jednej stronie są pomijane zawsze. Duplikaty w obrębie
jednego zestawu trafiają do pamięci raz. Po zakończeniu okno podsumowuje pracę:
*„Dopisano do pamięci: 5 par. • Gotowych par: 5 • puste: 1 • wiersze techniczne: 1”*.

**Kodowanie** jest domyślnie wykrywane automatycznie (UTF-8 z BOM i bez, cp1250,
ISO-8859-2, cp1252) — plik zapisany w Notatniku pod Windows nie zamieni polskich znaków
w krzaki. Gdy automat się pomyli albo plik jest w egzotycznym kodowaniu, wybierasz je
ręcznie z listy. Przycisk **⇄ Zamień strony** odwraca kierunek pary (razem z językami
i kodowaniem), gdy program pomylił źródło z tłumaczeniem.

Przy **nieparzystej liczbie plików** ostatni zostaje bez pary — program mówi o tym wprost
zamiast po cichu go pomijać.

**Pliki o tej samej nazwie z różnych katalogów** (`en/text.txt` + `pl/text.txt`) parują się
normalnie — również wtedy, gdy przeciągasz je **pojedynczo, jeden po drugim**. Pierwszy plik
czeka wtedy na partnera z komunikatem *„⏳ Czeka na parę: text.txt. Przeciągnij drugi plik
(może być z innego katalogu)”*. Wcześniej taki plik przepadał i para nigdy nie powstawała.

Program **nie łączy też plików o tym samym języku** — wrzucenie samego katalogu `en/` nie
utworzy fałszywych par `angielski → angielski`. Dopiero po dołożeniu `pl/` pliki dobierają
się po nazwie: `menu.txt` z `menu.txt`, `text.txt` z `text.txt`, niezależnie od kolejności
przeciągania.

## Pamięć TM — nazwy własne, warianty i kolejność

### „Zastosuj TM” pomijało segmenty mimo trafień 100%

Pamięć miała wpis, a segment zostawał pusty. Przyczyną był filtr odsiewający wpisy, w których
tłumaczenie jest kopią źródła — miał chronić przed niedokończoną pracą, ale w plikach gier
**mnóstwo wpisów jest identycznych z założenia**: `CINNABAR GYM`, `PP UP`, `TM01 FOCUS PUNCH`,
okrzyki `POLIWRATH: Ribi ribit!`. To świadome decyzje tłumacza, a filtr traktował je jak błąd.

Teraz decyduje **długość i obecność nazwy własnej**:

| Wpis | Wynik |
|---|---|
| `CINNABAR GYM` → `CINNABAR GYM` | ✅ przechodzi — krótki, wersaliki = nazwa własna |
| `PP UP` → `PP UP` | ✅ przechodzi |
| `POLIWRATH: Ribi ribit!` → to samo | ✅ przechodzi |
| `System.` → `System.` | ❌ odrzucony — krótki, bez nazwy własnej, nic nie wnosi |
| `Thank you for using the MYSTERY GIFT System.` → to samo | ❌ odrzucony — długie zdanie, praca niedokończona |

Zmierzone na tym samym zestawie: przed poprawką „Zastosuj TM” uzupełniało **1 z 4** segmentów,
po poprawce **4 z 4**.

### Kolejność wpisów i różne tłumaczenia tego samego tekstu

To samo zdanie angielskie bywa tłumaczone różnie zależnie od miejsca w grze
(`BALL` → `KULA` / `PIŁKA` / `BAL`). Wcześniej kolejny wpis **nadpisywał** poprzedni w indeksie,
więc zostawało wyłącznie ostatnie tłumaczenie z pliku — pozostałe znikały bezpowrotnie.
Do tego pamięć była sortowana po liczniku użyć, więc kolejność nie odpowiadała plikowi TM.

Teraz:

* **kolejność z pliku TM jest zachowana** — import, podgląd pamięci i eksport TMX pokazują
  wpisy dokładnie w tej kolejności, w jakiej były w pliku (`ORDER BY id`);
* **wszystkie warianty są zachowane** — pierwszy z pliku jest podpowiadany domyślnie
  („Zastosuj TM” bierze właśnie jego), a pozostałe widać na liście dopasowań TM
  jako osobne propozycje do wyboru;
* **ręczna poprawka tłumacza ma pierwszeństwo** — zapis `Ctrl+Shift+S` albo edycja w tabeli
  robi z Twojej wersji główną podpowiedź, zamiast dokładać kolejny wariant.

### Dopasowanie zdań — ostrzeżenie o niepełnym złożeniu

Propozycja mogła podmienić samą końcówkę i zostawić resztę po angielsku:

```
źródło:     Would you like to mix records with\nother TRAINERS?
propozycja: Would you like to mix records with\nINNE TRAINERS?   ← początek po angielsku!
```

Taka podpowiedź wygląda jak gotowe zdanie i łatwo ją zatwierdzić przez pomyłkę. Program
porównuje teraz wyrazy segmentu z wyrazami propozycji i gdy większość oryginału przetrwała,
oznacza wynik jako niepełny:

* pozycja jest **pomarańczowa** i opisana `⚠️ … • zostaje tekst źródłowy`,
* trafia **na koniec listy**, za propozycjami, które tłumaczą całość,
* **nigdy nie jest wstawiana automatycznie** (auto-wstawianie złożeń ją pomija).

Propozycje nie są usuwane — bywają przydatne jako podpowiedź samego terminu.

### Propozycja jest czystym tekstem — bez znaczników z pliku

Segment rzadko jest gołym zdaniem — na końcu bywa znacznik gry (`<<kon>>`), którego
**nie ma w tekście oryginalnym**. Propozycja go nie dostaje:

```segment:     when we decided to have 1 room.<<kon>>
propozycja:   gdy zdecydowaliśmy mieć 1 salę.           ← czysty tekst```

* na ekranie znaczniki (`<<kon>>`, `{PLAYER}`) i tak są ukryte — widać sam tekst,
  a pełną wersję po najechaniu myszą,
* z propozycji usuwane są znaczniki w podwójnych ostrokątach (`<<…>>`), których
  nie ma w tłumaczeniu z TM — wszystkie ścieżki dopasowania,
* **zostają** zmienne `{STR_VAR_1}` i kody wiersza `\n`, `\p` — niosą treść
  i są dopasowywane do oryginału.

Dodatkowo:

* ten sam tekst nie pojawia się **dwa razy** (osobno ze ścieżki dokładnej i rozmytej),
* propozycja z przełamanego segmentu dostaje przełamanie z powrotem,
  gdy tłumaczenie jest dłuższe niż najdłuższa linia oryginału.

### Podpowiedzi czyta się bez znaczników

W panelu „Dopasowanie zdań” propozycja jest pokazywana **bez** `<<kon>>`, `{PLAYER}`
i podobnych kodów — widać sam tekst, o który chodzi. Do tłumaczenia trafia
pełna wersja, czyli z kodami oryginału (jak wyżej), a surowy tekst jest w
podpowiedzi po najechaniu myszą na pozycję.

Dodatkowo odrzucane są dopasowania „z niczego”: jeśli jedyną wspólną rzeczą
między segmentem a wpisem pamięci jest cyfra (segment „…mieć **1** salę.” wobec
wpisu „just **one** / tylko **1**”), taka propozycja w ogóle się nie pojawia.

### Skróty klawiszowe a polskie znaki

Na polskiej klawiaturze `AltGr` + litera daje polski znak (ę, ś, ń, ó, ł, ż, ź, ć, ą),
a Qt widzi to jako **Ctrl+Alt+litera**. Każdy taki skrót programu „zjadał” wpisywane
litery — `Ctrl+Alt+E` zamiast „ę” otwierał edytor TMX.

Dlatego **żaden domyślny skrót nie używa już Alt z literą**; dziesięć poleceń
przeniesiono na `Ctrl+Shift+…`:

| Polecenie | Dawniej | Teraz |
|---|---|---|
| Poprzedni nieprzetłumaczony | Ctrl+Alt+U | Ctrl+Shift+U |
| Następny przetłumaczony | Ctrl+Shift+U | Ctrl+Shift+Y |
| Następny niezatwierdzony | Ctrl+Alt+N | Ctrl+Shift+A |
| Przywróć wcięcie | Ctrl+Alt+W | Ctrl+Shift+W |
| Następny „do przetłumaczenia” | Ctrl+Alt+T | Ctrl+Shift+G |
| Szukaj w tym pliku | Ctrl+Alt+F | Ctrl+Shift+E |
| Sprawdź język | Ctrl+Alt+J | Ctrl+Shift+J |
| QuickTrans | Ctrl+Alt+Q | Ctrl+Shift+Q |
| Edytor TMX | Ctrl+Alt+E | Ctrl+Shift+X |
| Kopiuj pomiar czasu | Ctrl+Alt+T | Ctrl+Shift+P |

Gdy sam ustawisz skrót z Alt i literą (Ustawienia → Skróty), program ostrzeże, że
taka kombinacja blokuje polskie znaki. Dodatkowo przy starcie aplikacja oddaje
`Ctrl+Alt+literę` polom tekstowym (filtr `ShortcutOverride`), więc **ę, ś, ą, ć, ł,
ń, ó, ź, ż** wpiszesz nawet wtedy, gdy jakiś skrót koliduje z AltGr.

### Odstępy przy kodach wiersza

Wpis w pamięci bywa zapisany z odstępem przed przełamaniem, którego nie ma
w oryginale — po wstawieniu spacja zostaje i psuje tekst w grze:

```oryginał:   …even a crash with a jet\nplane won't leave a scratch.
wpis w TM:  …że nawet \nzderzenie nie pozostawi zadrapania.
                      ^ spacja, której nie ma w oryginale
po wstawieniu: …że nawet\nzderzenie nie pozostawi zadrapania.```

Program przycina odstępy przy kodach tak, żeby zgadzały się z oryginałem (spacja
znika tylko wtedy, gdy w oryginale też jej nie ma). **Wyłącznik:** ustawienie
`tm.adapt.break.spaces` (domyślnie włączone).

### Słownik z odmianą

`pl_PL.dic` (LibreOffice) zawiera wyłącznie **formy podstawowe** — bez reguł
odmiany poprawne słowa (`ofiarę`, `zamrozić`, `jeźdząc`, `chmurę`) są zgłaszane
jako błędy. Działają dwa sposoby:

1. **„polski – pełna odmiana, 4,5 mln form (SJP.pl) ★ zalecany”** — zakładka
   *📖 Słowniki → ⬇ Pobierz słownik…*. Lista ma wszystkie formy wypisane wprost,
   więc działa nawet bez Hunspella.
2. **Silnik Hunspell** — wymaga biblioteki `spylls` (`pip install spylls`) i pliku
   `.aff` obok `.dic`; program pobiera go automatycznie razem ze słownikiem.

Zakładka *Słowniki* pokazuje od razu, z czym pracujesz: „✅ pełna odmiana
(Hunspell: pl_PL.dic)”, „✅ pełna odmiana (lista zawiera formy odmienione)” albo
„⚠️ tylko formy podstawowe – poprawne słowa („ofiarę”, „zamrozić”, „jeźdząc”)
będą zgłaszane jako błędy”.

### Oznaczenie „do przetłumaczenia” i powrót do miejsca pracy

* **🔵 do przetłumaczenia** — nowe oznaczenie segmentu (menu podręczne w siatce
  *🏷️ Oznacz jako…*, menu *Projekt*, skrót `Ctrl+Shift+T`). Działa jak „wrócę tu
  później”: filtr **Do przetłumaczenia** pokazuje tylko takie segmenty, a skrót
  `Ctrl+Shift+G` skacze między nimi.
* **Pamięć miejsca pracy** — program zapamiętuje, na którym segmencie skończyłeś,
  **osobno dla każdego pliku** (ustawienie `editor.last.segment`). Po wejściu
  w plik — i po ponownym otwarciu projektu — wraca do tego samego segmentu,
  zamiast zaczynać od pierwszego.

## Pilnowanie, żeby w TM były tylko prawdziwe tłumaczenia

*Ustawienia → 💾 Pamięć TM → **„Nie zapisuj do TM tekstów, które zostały w języku źródłowym”***

W plikach gier częsty problem: część tekstu nie jest jeszcze przetłumaczona, a mimo to trafia
do pamięci. Potem TM podpowiada angielski na angielski i „Zastosuj TM” wypełnia nim segmenty.

Po włączeniu opcji program rozpoznaje język tłumaczenia i **odrzuca wpis**, jeśli został on
w języku źródłowym. Rozpoznawanie opiera się na dwóch sygnałach:

* **polskie znaki** (`ą ć ę ł ń ó ś ź ż`) i typowe polskie wyrazy funkcyjne
  (`jest`, `nie`, `czy`, `masz`, `dziękuję`…) — tekst jest uznany za przetłumaczony;
* **angielskie wyrazy funkcyjne** (`the`, `you`, `would`, `game`…) bez śladu polszczyzny —
  tekst jest uznany za nieprzetłumaczony.

| Wpis | Wynik |
|---|---|
| `Save the game` → `Zapisz grę` | ✅ zapisany |
| `Save the game` → `Save the game now` | ❌ odrzucony — nadal angielski |
| `Would you like to save?` → to samo | ❌ odrzucony |
| `CINNABAR GYM` → `CINNABAR GYM` | ✅ zapisany — krótka nazwa własna |
| `other TRAINERS` → `inni TRENERZY` | ✅ zapisany — angielska nazwa w polskim zdaniu nie przeszkadza |

Opcja działa przy **zapisie segmentu** (`Ctrl+Shift+S`), **imporcie TMX** i w **generatorze TM
z plików** (tam ma też własny przełącznik, żeby dało się użyć jej jednorazowo bez zmiany
ustawień globalnych). Domyślnie jest wyłączona — włącz ją, gdy pracujesz na materiale
częściowo przetłumaczonym.

> Różnica wobec sąsiedniej opcji **„Ukrywaj wpisy nieprzetłumaczone”**: tamta tylko chowa takie
> wpisy w podpowiedziach, ta **nie wpuszcza ich do pamięci w ogóle**.

## Ustawienia pamięci TM

Zakładka *Ustawienia → **💾 Pamięć TM*** ma teraz jasne nazwy i komplet wyłączników:

| Grupa | Przełączniki |
|---|---|
| **🔍 Podpowiedzi z pamięci TM** | **włącz/wyłącz podpowiedzi** (nowe) • próg dopasowania • liczba wyników • zapis do TMX • dopasowywanie tagów • **dopasowanie przełań (\n, \p) do oryginału** (nowe) • **auto-detekcja kodów gry z tekstu + wklejona lista kodów** (nowe) • **wielkość liter fragmentów wg oryginału + kody dla za długiego tłumaczenia** (nowe) • ukrywanie wpisów nieprzetłumaczonych |
| **🔗 Dopasowanie zdań** | składanie z fragmentów • minimalne podobieństwo • wyłączenie przy dużej pamięci • szukanie w segmentach projektu • automatyczne wstawianie złożenia |
| **✍️ Automatyczne wstawianie** | wstawianie do pustego segmentu • **nadpisywanie istniejącego tłumaczenia** (nowe) • **zapis zatwierdzonego segmentu do TM** (nowe) |
| **⚡ Automatyka po wczytaniu plików** | uzupełnianie z TM • tłumaczenie maszynowe reszty • pytanie o zgodę |

Podopcje zależne od przełącznika są wcięte (`↳`), a nazwy mówią, co faktycznie się stanie —
np. zamiast „Adaptuj tagi w podpowiedziach TM” jest „Dopasowuj tagi i znaczniki do bieżącego
segmentu”.

## Masowe oznaczanie: zakresy TM01–TM66 i teksty po japońsku

*Projekt → **🏷️ Oznacz pasujące do wzorca…***

Jedno okno załatwia zadania, które wcześniej wymagały klikania segment po segmencie.

### Zakresy numerowane

Zamiast wpisywać 66 osobnych wzorców, podajesz **`TM01-TM66`** — program rozwija zakres sam:

| Wzorzec | Obejmuje |
|---|---|
| `TM01-TM66` | TM01, TM02, … TM66 (66 nazw) |
| `HM01-HM28` | HM01 … HM28 (28 nazw) |
| `HM1-HM3` | HM1, HM2, HM3 — bez zer wiodących |

Dopasowanie jest **dokładne**: `TM1` nie zostanie wzięte za `TM01`, a `TM67` nie wpadnie do
zakresu `TM01-TM66`. Nazwa jest też znajdowana wewnątrz zdania („Otrzymałeś **TM05** od lidera”).

Przy oznaczaniu jako *przetłumaczone* działa przełącznik **„Wstaw tekst źródłowy jako
tłumaczenie”** — nazwy typu `TM01` zostają bez zmian, więc segment jest naprawdę gotowy,
a nie tylko oznaczony. Bez tego licznik postępu pokazywałby pracę, której nikt nie wykona.

### Teksty pozostawione po japońsku / chińsku / koreańsku

Segment w rodzaju:

```
ポケモンに　きのみを\nもたせて　おけば\lたたかっている　ときに
```

nie ma po co trafiać do tłumaczenia z polskiego projektu. Wybierz gotowy wzorzec
**„Teksty po japońsku / chińsku / koreańsku”** i oznacz je jako **pominięte** — jednym
kliknięciem, dla całego projektu.

Program rozpoznaje hiraganę, katakanę, hanzi (chiński i kanji), hangul oraz japońską
interpunkcję i znaki pełnej szerokości. Znaczniki `\n`, `\p`, `\l` i teksty łacińskie
nie są mylnie wykrywane.

Reguła CJK jest **domyślnie włączona** i dostaje się automatycznie także do projektów
utworzonych wcześniej (brakujące reguły wbudowane są doklejane przy otwarciu, bez
dotykania reguł własnych) — więc tekst po japońsku/chińsku jest oznaczany jako
pominięty od razu po wczytaniu plików, bez żadnej konfiguracji. W *Ustawienia →
Wykluczenia* można ją obejrzeć i wyłączyć.

### Jak to działa

| Element okna | Do czego służy |
|---|---|
| **Gotowe** | trzy gotowce: TM01–TM66, HM01–HM28, znaki CJK |
| **Wzorzec** | zakres, gwiazdka (`<<< FILE:*>>>`) albo zwykły fragment tekstu |
| **Dopasuj** | tryb — domyślnie *automatycznie* rozpoznaje zakres po myślniku |
| **Oznacz jako** | przetłumaczony ★ zatwierdzony 🚫 pominięty ✎ roboczy |
| **podgląd** | lista pasujących segmentów **przed** zatwierdzeniem, z licznikiem |
| **zapisz jako regułę** | wykluczenie zadziała także po ponownym wczytaniu plików |

Podgląd aktualizuje się na bieżąco, więc widać dokładnie, co zostanie oznaczone, zanim
klikniesz „Oznacz”. Operację można cofnąć (`Ctrl+Z`).

Wzorzec CJK jest też dostępny jako **gotowa reguła wykluczania**
(*Ustawienia → Wykluczenia*), gdy chcesz, żeby działał automatycznie przy każdym imporcie.

## Dopasowanie znaczników do oryginału (\n, \l, \p)

W plikach gier tłumaczenie ma się przełamywać w zbliżonych miejscach co oryginał,
bo linia dialogu ma określoną szerokość. Do tej pory znaczniki `\n`/`\p` trzeba
było przenosić ręcznie, a wpisy w TM często miały angielski z przełamaniami, a
polskie tłumaczenie bez żadnego kodu.

**Podpowiedzi TM** robią to teraz same (ustawienie *Ustawienia → Pamięć TM →
„Dopasowuj przełamania (\n, \p) w podpowiedziach do oryginału”*, domyślnie
włączone):

```
TM:  en  A strange seed was planted on its back at\n
      birth. The plant sprouts and grows with\nthis POKéMON.
      pl  Dziwne nasiono zostało zasadzone na jego plecach od
          urodzenia. Roślina się rozwija i rośnie z tym Pokémonem.

podpowiedź po dopasowaniu:
      Dziwne nasiono zostało zasadzone na jego plecach\n
      od urodzenia. Roślina się rozwija i rośnie z\n
      tym Pokémonem.
```

* wiersze dostają `\n` w miejscach **proporcjonalnych** do długości wierszy
  oryginału, zawsze na granicy wyrazów (w tekście CJK — dokładnie w miejscu
  proporcji, bo chiński/japoński można łamać w dowolnym miejscu),
* `\p` (akapity) przenoszone 1:1 — jeśli w tłumaczeniu jest mniej akapitów,
  brakujących `\p` program **nie wymyśla**,
* treść i wiodące/końcowe spacje (wcięcie dialogu) zostają nietknięte,
* tłumaczenie, które ma już tę samą strukturę kodów, nie jest ruszane,
* **kody są do wyboru**: domyślnie wiersz to `\n` / `\l`, a akapit `\p`,
  ale Twoja gra może używać innych znaczników — wpisz je w *Ustawienia →
  Pamięć TM → „Kody do dopasowania”* (pole **Wiersz** i **Akapit**, np.
  `\N \L` albo `\page`) i dopasowanie będzie operować na nich zamiast
  na domyślnych. Działa to w podpowiedziach TM i w akcji „⇢ Dopasuj
  znaczniki do oryginału”. Domyślne `\n`, `\l`, `\p` to przykłady,
  nie ograniczenie.
* **auto-detekcja kodów** — program sam rozpoznaje kody w tekście, bez
  żadnych ustawień: znacznik z backslashem (`\N`, `\x1B` — backslash +
  znak), zmienna w klamrach (`{USER_1}`) i tag w podwójnych nawiasach
  (`<<SKOK>>`). Jeśli kodu nie ma w polach Wiersz/Akapit, jest doklejany
  automatycznie (kody typu `\p`/`\Page` trafiają do akapitów), więc np.
  `\N` w oryginale wyląduje w podpowiedzi jako `\N` — w tamtym samym
  miejscu co w oryginale.
* **wklejona lista kodów** — pole *Lista kodów* w tym samym grupie ustawień:
  wklej tam wszystkie znaczniki, które w Twojej grze mają znaczenie
  (spacjami lub liniami, np. `\n \l {VAR} <<TAG>>`). Puste pole = pełna
  auto-detekcja; wypełniona lista = dokładnie te kody (auto-detekcja
  wyłączona). Przycisk **„Auto-wykryj z pliku”** skanuje otwarty projekt
  i wypełnia listę tym, co program rozpoznał w źródłach i tłumaczeniach.
* **ulepszona lokalizacja przełamania** (włączana osobno, domyślnie ON) —
  zamiast łamać „po proporcji długości”, program pasuje wyrazy tłumaczenia
  do wierszy oryginału i wstawia kod tam, gdzie faktycznie leży ich
  odpowiednik (wygrywa lepszy z dwóch układów, ocenionych tym samym
  kryterium — nie jest nigdy gorzej niż proporcja).
* **poprawa podwójnych backslashów** (włączana osobno, domyślnie ON) —
  niektóre ekstraktyory zapisują kody jako `\\n` zamiast `\n`; przy
  wczytywaniu pliku program kurczy parzyste serie backslashów przed literą
  do jednego, więc kody są rozpoznawane, dopasowywane i zapisywane
  w prawidłowej postaci.
* **wielkość liter fragmentów z TM** — fragment podstawiany z pamięci
  dostaje wielkość liter z oryginału: „No special **ability**.” + wpis TM
  „ABILITY → ZDOLNOŚĆ” daje „zdolność”, nie „ZDOLNOŚĆ” (CAŁE SŁOWO w
  oryginale → wielkie litery; pojedyncze słowo z wielką pierwszą → wielka
  pierwsza). Mieszane wielkości (nazwy własne) nie są ruszane.
* **kody dla za długiego tłumaczenia** (włączane osobno, domyślnie ON) —
  oryginał bez przełamań, a tłumaczenie mu wyrosło? Program dokleja `\n`
  przy spacji tak, by każda linia mieściła się w szerokości oryginału
  (w grze za długi wiersz nie wyświetli się w całości).
* **czytelne etykiety dopasowania zdań** — „pokrycie 100%” (czyli: propozycja
  zamienia cały segment) pokazywane jest jako **„całość segmentu”**, żeby nie
  mylić udziału tekstu z jakością dopasowania (ona jest w „~NN%”).
* **case WNIETRZ linii** — jeśli TM trzyma wiersz z CAŁYM SŁOWEM po
  środku zdania („No special **ZDOLNOŚ**.”), a w oryginale to słowo ma
  małe litery („No special **ability**.”), podstawiane tłumaczenie dostaje
  wielkość liter z oryginału (słowo po słowie, gdy oba wiersze mają tyle
  samo słów).

Do segmentów, które już przetłumaczono, służy działanie w siatce: **klik
prawy → „⇢ Dopasuj znaczniki do oryginału”** (działa na wszystkich
zaznaczonych wierszach na raz, da się cofnąć `Ctrl+Z`). Z tego samego menu
dostępne jest też **„🏷️ Oznacz pasujące do wzorca…”** — czyli okno z zakresami
`TM01-TM66` i wzorcem CJK, bez szukania go w menu *Projekt*.

## Wykluczanie segmentów technicznych

W plikach gier obok tekstu do tłumaczenia stoją wiersze techniczne:

```
<<< FILE: CeladonCity_Condominiums_RoofRoom/text.inc >>>
#org @8005A2
[POKEMON_NAME]
```

Zakładka *Ustawienia → **🚫 Wykluczenia*** pozwala je odsiać. System jest
**uniwersalny** — wzorce są tylko przykładami, a każdą regułę możesz dopasować do swoich
plików (dowolny tekst, gwiazdka, zakres, regex). Segmenty pasujące do reguł są
oznaczane zgodnie z jej **działaniem**:

| Działanie | Efekt |
|---|---|
| **🚫 pominięte** (domyślne) | segment nie trafia do tłumaczenia maszynowego, do pamięci TM ani do statystyk „pozostało do zrobienia” |
| **★ przetłumaczone** | segment uznawany za gotowy — do statystyk „połowicznie/ukończone”, nie do tłumaczenia (np. wzorce `CHEM*`, które zostają bez zmian, ale są „przetłumaczone”) |

**Treść zostaje nietknięta** i wraca do pliku przy eksporcie.

**Reguła składa się z wzorca, sposobu dopasowania i działania:**

| Sposób | Przykład | Znaczy |
|---|---|---|
| **wzorzec z gwiazdką** | `<<< FILE:*>>>` | dowolna nazwa pliku w środku |
| zawiera tekst | `#org` | gdziekolwiek w segmencie |
| zaczyna się od | `#` | tylko na początku |
| kończy się na | `>>>` | tylko na końcu |
| jest dokładnie równy | `{STR_VAR_1}` | cały segment |
| wyrażenie regularne | `^\s*#\w+` | pełna kontrola |
| zakres numerowany | `TM01-TM66` | TM01 … TM66 jedną regułą |

Każdą regułę można **włączyć lub wyłączyć osobno** (kratka „✓”), ograniczyć do wybranego
pliku, opisać komentarzem, ustawić rozróżnianie wielkości liter i **wybrać działanie**
(pominięte / przetłumaczone). Tabela pokazuje **liczbę trafień** dla każdej reguły, a panel
poniżej — **listę segmentów**, które zostaną oznaczone, zanim cokolwiek zatwierdzisz.

Przykład uniwersalnego zastosowania: wzorce chemiczne w pliku `CHEM-001`, `CHEM-002`…
nie wymagają tłumaczenia, ale są elementem ukończonym — reguła `CHEM*` (działanie:
**przetłumaczone**) oznacza je wszystkie za jednym zamachem. Na odwrót: `#org` (działanie:
**pominięte**) nie liczy się ani w tłumaczeniu, ani w statystykach.

**📋 Gotowe wzorce…** dodają reguły typowe dla plików gier: nagłówki `<<< FILE: … >>>`,
znaczniki `<<< … >>>`, dyrektywy `#org`, segmenty będące samą zmienną `{STR_VAR_1}`,
etykiety `[NAZWA]`, ścieżki plików, segmenty bez ani jednej litery,
**teksty po japońsku / chińsku / koreańsku** (działanie: pominięte) oraz
**wzory `CHEM…`** (działanie: przetłumaczone).

Reguły wbudowane są **dostarczane automatycznie**: projekt utworzony starszą
wersją programu dostaje nowe gotowce przy pierwszym otwarciu (własne reguły
zostają nietknięte). Każdą — włącznie z wbudowanymi — możesz wyłączyć
kratka „✓” albo zmienić jej wzorzec i działanie.

Reguły zapisują się w pliku projektu i działają **automatycznie przy wczytywaniu plików**.
Okno edycji sprawdza wzorzec **na żywo** na przykładowych wierszach, pokazując osobno
„🚫 POMINIĘTE” (lub „★ PRZEZŁUMACZONE”, zależnie od działania) i „✅ BEZ ZMIAN”;
błędne wyrażenie regularne blokuje zapis. Gdy segment pasuje do kilku reguł,
liczy się **pierwsza** z listy — kolejność w tabeli ma znaczenie.

### Cofanie wykluczeń — działa w obie strony

Reguły nie są jednokierunkowe. **Każde wykluczenie da się cofnąć, także grupowo**,
a Twoja decyzja jest ważniejsza od reguły:

| Sytuacja | Co się dzieje |
|---|---|
| Reguła wykluczyła segment, Ty go **przywracasz** | zostaje przywrócony — reguła **nie zabierze go ponownie**, nawet po `F5` i ponownym wczytaniu plików |
| Pominąłeś segment **ręcznie**, reguła przestała pasować | zostaje pominięty — automat go nie przywróci |
| Chcesz zacząć od zera | **🧹 Skasuj ręczne wyjątki** — program zapomina o Twoich decyzjach i stosuje reguły od nowa |

Do cofania służą:

* **↩️ Przywróć zaznaczone (N)** w menu siatki — grupowo, dla zaznaczonych wierszy (`Ctrl+Shift+R`),
* **↩️ Przywróć pominięte w tym pliku** — cały plik naraz,
* **↩️ Przywróć WSZYSTKIE pominięte (N)** — w menu siatki, w menu **📦 Projekt** oraz jako
  przycisk w zakładce **🚫 Wykluczenia**.

Decyzje zapisują się w projekcie (`translations.json`), więc przetrwają zamknięcie programu.

### Grupowe pomijanie segmentów

Segmenty można pomijać także ręcznie, **wiele naraz**. Siatka przyjmuje zaznaczenie
wielokrotne (`Ctrl`+klik, `Shift`+klik, `Ctrl+A`), a prawy przycisk myszy daje:

| Pozycja menu | Działanie |
|---|---|
| **🚫 Pomiń zaznaczone (N)** | oznacza wszystkie zaznaczone jako pominięte |
| **↩️ Przywróć zaznaczone (N)** | cofa pominięcie (`Ctrl+Shift+R`) |
| **🔁 Odwróć pominięcie** | mieszane zaznaczenie → pomija wszystkie; same pominięte → przywraca |
| **🚫 Pomiń nieprzetłumaczone w tym pliku…** | jednym ruchem odsiewa resztę pliku |
| **🚫 Pomiń pasujące do wzorca…** | wpisujesz np. `<<< FILE:*>>>`, program pokazuje ile pasuje i proponuje **zapisanie jako stałej reguły** |

Skróty: `Ctrl+Shift+I` pomija zaznaczone, `Ctrl+Shift+R` przywraca. To samo jest w menu
**📦 Projekt** i pod przyciskiem **🚫 Pomiń** w pasku pod edytorem.

**Pominięte segmenty nie są liczone.** Znikają z mianownika w liczniku pliku, w pasku
postępu i w statystykach — bez dodatkowych oznaczeń, same liczby:

```
📚 Wszystkie pliki (3/6)
📄 miasto.txt  (3/4 • 75%)
📄 sklep.txt   (0/2 • 0%)
```

## Układ paneli — nie da się ich zgubić

Panele w Edytorze (**Pliki projektu**, siatka segmentów, prawa kolumna z pomocą tłumacza)
rozsuwa się myszą, chwytając pasek między nimi. Wcześniej dało się przeciągnąć taki pasek
do samej krawędzi — panel **znikał całkowicie i nie było jak go przywrócić**, bo uchwyt
zlewał się z brzegiem okna.

Poprawione:

| Zmiana | Efekt |
|---|---|
| **blokada zwijania** | panel nie schowa się do zera — zatrzymuje się na minimalnej szerokości |
| **minimalne rozmiary** | 150 px dla listy plików, 320 px dla siatki, 180 px dla prawej kolumny |
| **szerszy uchwyt (6 px)** | łatwiej go trafić myszą; podświetla się na niebiesko pod kursorem |
| **↺ Przywróć układ paneli** | *Widok → ↺ Przywróć układ paneli* rozsuwa wszystko do proporcji domyślnych |

To samo zabezpieczenie działa w panelu **AI** i w **edytorze TMX**, gdzie panele dzielą się
w pionie.

### Przełączanie układu prawej kolumny (wszystko naraz / zakładki)

Wybór układu jest w *Ustawienia → Wygląd → Panel prawy edytora*. Przełączanie działa teraz
bez dwóch przykrych skutków, które zgłaszano:

| Dawniej | Teraz |
|---|---|
| po zmianie układu prawa kolumna zwężała się do minimum (180 px) | **szerokość zostaje taka, jaką ustawiłeś** — splitter nie przelicza jej od nowa |
| panele po przełączeniu zostawały ukryte (prawa strona „nic nie wyświetlała”) | **każdy panel jest pokazywany z powrotem** po włożeniu do nowego kontenera |

Powód drugiego był w Qt: wypięcie widgetu (`setParent(None)`) chowa go „na sztywno”, a
`QTabWidget` dodatkowo chowa wszystkie karty poza bieżącą — po powrocie do układu
„wszystko naraz” żaden panel już nie wracał na ekran.

### Wysokość paneli po prawej

W układzie „wszystko naraz” panele (Dopasowania TM, Dopasowanie zdań, Terminy,
Konkordancja, MT, Język, Notatki) dzieliły się po równo i **nie było czego złapać** —
nie dało się powiększyć „Dopasowań TM” kosztem pozostałych. Teraz między panelami jest
widoczny uchwyt (8 px, ten sam styl co w kolumnach edytora):

* przeciągasz, żeby powiększyć panel, nad którym pracujesz,
* wysokości są **zapamiętywane** (ustawienie `editor.panel.heights`) i wracają po
  przełączeniu układu oraz po ponownym uruchomieniu,
* żaden panel nie da się zwinąć do zera (minimum 60 px),
* *Widok → ↺ Przywróć układ paneli* wraca do równego podziału.

### Czcionki — prawy panel i cały interfejs

| Ustawienie (Ustawienia → Wygląd) | Co zmienia |
|---|---|
| **Czcionka interfejsu** (`ui.font.size`) | wielkość czcionki w **całym programie**: menu, zakładki, tabele, przyciski, listy. 0 = domyślna z motywu. Skróty: `Ctrl+Shift++` / `Ctrl+Shift+−` |
| **Rozmiar czcionki edytora** (`editor.font.size`) | tylko pola źródła i tłumaczenia (`Ctrl++` / `Ctrl+−`) |
| **Czcionka paneli** (`tm.panel.font.size`) | **cały prawy panel** — listy, etykiety, przyciski, podgląd MT, notatki (dawniej tylko cztery listy, więc zmiana była ledwo widoczna) |

| **Czcionka pojedynczego panelu** (`tm.panel.font.matches`, `.sentences`, `.terms`, `.conc`, `.mt`, `.lang`, `.notes`) | rozmiar dla **jednego** wybranego panelu: np. tylko „Dopasowania TM” albo tylko „Dopasowanie zdań”. Zero = rozmiar wspólny / z interfejsu |

Wszystkie suwaki są w jednej grupie **„🔤 Czcionka paneli po prawej”**, a pod nimi
przycisk *↺ Domyślne (wszędzie zero)*, który wraca do normalnej wielkości. Wcześniej
nagłówki grup w Ustawieniach miały na sztywno 11 px i szary kolor — przez to opcje
czcionek były nieczytelne i nie dało się ich znaleźć; teraz nagłówki mają zwykłą
wielkość, a grupa z motywem nazywa się „🎨 Motyw i czcionki”.

Zmiana działa od razu, bez restartu. Gdy czcionka panelu jest ustawiona na 0, panel
rośnie razem z czcionką interfejsu.

### Zastosuj TM ponownie (także do przetłumaczonych)

Zwykłe „Zastosuj TM” uzupełnia tylko puste segmenty. Gdy do pamięci doszły lepsze
wpisy, przydaje się druga opcja — w menu podręcznym **listy plików** (prawy przycisk
na pliku) oraz w menu *Projekt*:

> 🔁 **Zastosuj TM ponownie – „plik” (N z tłumaczeniem)**

Podmienia istniejące tłumaczenia na najlepsze dopasowanie z TM. Przed zmianą program
pyta, ile segmentów obejmie. Segmentów **★ zatwierdzonych nie rusza**, a status
przetłumaczonego segmentu nie spada do „roboczego”.

## Szerokości kolumn siatki segmentów

Kolumny siatki (`#`, **Tekst źródłowy**, **Tłumaczenie**, **Status**) przesuwa się myszą,
chwytając krawędź w nagłówku:

* przesunięcie krawędzi **rozszerza jedną kolumnę, a sąsiad oddaje jej miejsce** — siatka
  zawsze mieści się w oknie, nie pojawia się poziomy pasek przewijania,
* przy zmianie szerokości okna wolne miejsce dzielone jest **proporcjonalnie** do tego,
  jak ustawiłeś kolumny (domyślnie pół na pół między źródłem a tłumaczeniem),
* szerokości są **zapamiętywane** (ustawienie `editor.grid.columns`) i wracają po
  ponownym uruchomieniu programu,
* **prawy przycisk na nagłówku** → *↔ Dopasuj kolumny do okna* albo
  *↺ Domyślne szerokości kolumn* (55 / 400 / 400 / 150 px).

Dawniej dwie środkowe kolumny były w trybie `Stretch`, a w tym trybie Qt w ogóle nie pozwala
zmienić szerokości — nawet programowo — więc kolumn naprawdę „nie dało się” przesunąć.

## Pliki projektu — zaznaczanie wielu i kolejność

Panel **📁 Pliki projektu** (po lewej w Edytorze) obsługuje teraz pracę na wielu plikach naraz.

**Zaznaczanie wielu** — `Ctrl+klik` dokłada pojedynczy plik, `Shift+klik` zaznacza zakres.
Obok przycisków widać licznik („zaznaczono 3”).

**Usuwanie kilku plików jednym ruchem** — przycisk 🗑️ albo menu podręczne
*„Usuń zaznaczone pliki (3) z projektu”*. Program pyta **raz** i wypisuje, co usunie:

```
Usunąć 3 plików z projektu?
  • miasto_1.txt
  • miasto_2.txt
  • dialogi.txt

Pliki zostaną skasowane z folderu source/ (42 segmentów).
⚠️ 12 z 42 segmentów ma tłumaczenia — zostaną utracone.
```

Ostrzeżenie o utracie tłumaczeń pojawia się tylko wtedy, gdy naprawdę coś jest do stracenia.
Odmowa nie usuwa niczego, a gdy któregoś pliku nie da się skasować, reszta i tak zostaje
usunięta, a program mówi, co się nie udało.

**Zmiana kolejności** — na dwa sposoby:

* **przeciągnij plik na liście** i upuść w nowym miejscu (działa też dla kilku zaznaczonych
  naraz — blok przenosi się w całości, zachowując wzajemny układ),
* przyciski **▲ ▼**, gdy wolisz klawiaturę i myszkę bez przeciągania.

**🔤** przywraca porządek alfabetyczny. Te same polecenia są w menu podręcznym.

Program rozróżnia **dwa rodzaje przeciągnięcia**: pliki z pulpitu trafiają do projektu
(import), a przeciąganie wewnątrz listy zmienia kolejność. Pozycja **„Wszystkie pliki”**
jest nieruchoma — nie da się jej przesunąć ani wstawić pliku nad nią.

| Zachowanie | Szczegół |
|---|---|
| **blok plików** | kilka zaznaczonych plików przesuwa się razem (▲▼ i przeciągnięciem), zachowując wzajemny układ |
| **krawędzie** | przy pierwszym/ostatnim pliku ruch jest blokowany — nic się nie „zawija” |
| **zaznaczenie** | po przesunięciu pliki zostają zaznaczone, więc da się klikać ▲ wielokrotnie |
| **segmenty** | kolejność segmentów w siatce zmienia się razem z plikami |
| **trwałość** | ustawienie zapisuje się w `.scproj` i przeżywa restart programu oraz `F5` |
| **nowy import** | świeżo dodany plik trafia **na koniec** i nie przestawia tego, co ułożyłeś |
| **usunięty plik** | znika też z zapisanej kolejności, nie zostawia „ducha” |

Dopóki nie ruszysz kolejności ręcznie, lista jest alfabetyczna, a w pliku projektu nie zapisuje
się nic zbędnego. Przycisk 🔤 kasuje ręczne ustawienie i wraca do alfabetu.

## Oznaczanie segmentów i nawigacja

**Wszystkie oznaczenia działają na wielu segmentach naraz.** Zaznaczasz wiersze
(`Ctrl`/`Shift`+klik, `Ctrl+A`), prawy przycisk → **🏷️ Oznacz jako…** i wybierasz:

| Status | Znaczenie |
|---|---|
| ○ **nowy** | do zrobienia od początku — zdejmuje wcześniejsze oznaczenia |
| ✎ **roboczy** | tłumaczenie wstępne, do sprawdzenia |
| ✓ **przetłumaczony** | gotowe |
| ★ **zatwierdzony** | sprawdzone i zamknięte |

Segment **zatwierdzony liczy się jako wykonany**, nawet gdy pole tłumaczenia jest puste —
np. gdy świadomie zostawiasz tekst bez zmian. Statusy są też w menu **📦 Projekt →
🏷️ Oznacz zaznaczone jako**, a zmiany zapisują się od razu.

Przycisk **✔ Zatwierdź i dalej** (`Ctrl+Enter`) **zawsze zmienia oznaczenie** segmentu na
„przetłumaczony” — także wtedy, gdy tłumaczenie jest celowo puste — i przechodzi do
**kolejnego segmentu do zrobienia**, pomijając gotowe i pominięte.

**Skróty nawigacji jak w OmegaT:**

| Skrót | Działanie |
|---|---|
| `Ctrl+U` | następny **nieprzetłumaczony** segment |
| `Ctrl+Shift+U` | poprzedni nieprzetłumaczony |
| `Ctrl+Shift+Y` | następny **przetłumaczony** |
| `Ctrl+Shift+A` | następny **niezatwierdzony** |

Skoki **zostają w przeglądanym pliku**: gdy masz otwarty jeden plik z listy, `Ctrl+U`
i przyciski **◀◀** / **▶▶** szukają tylko w nim i zawijają się w jego obrębie. Dopiero
kiedy w pliku nie ma już celu, program **pyta**, czy przejść do innego — wcześniej po cichu
podmieniał filtr i wyrzucał do zupełnie innego tekstu. Skoki omijają segmenty pominięte
i odsłaniają cel ukryty filtrem statusu.

### Cofanie zmian

`Ctrl+Z` cofa **nie tylko tekst**, ale też **zmiany oznaczeń**: statusy (nowy / roboczy /
przetłumaczony / zatwierdzony) oraz pominięcia — również te wykonane grupowo na wielu
segmentach naraz. `Ctrl+Y` ponawia.

Skrót **działa z klawiatury także wtedy, gdy kursor stoi w polu tłumaczenia**. Wymagało to
przechwycenia klawisza w `eventFilter`: `QPlainTextEdit` obsługuje `Ctrl+Z` samodzielnie
i nie przepuszczał go dalej, więc cofanie oznaczeń dawało się wywołać tylko z menu.
Kolejność jest naturalna — najpierw cofa się wpisany tekst, a gdy nie ma już czego cofać,
wracają poprzednie oznaczenia. Historia pamięta 100 operacji i czyści się przy zmianie projektu.

### Własne skróty klawiszowe

Zakładka *Ustawienia → **⌨️ Skróty*** pozwala zmienić **każdą** z 37 kombinacji.
Dwuklik w kolumnie „Skrót”, naciśnięcie nowej kombinacji i gotowe — zmiana działa
**bez restartu**. Kolumna „Domyślny” pokazuje wartość fabryczną, a zmienione wpisy są
wyróżnione kolorem. Program ostrzega, gdy kombinacja jest już zajęta, i pozwala ją przejąć.
Przyciski: **🚫 Wyłącz skrót**, **↺ Przywróć domyślny**, **↺ Przywróć wszystkie domyślne**.
Tabela zajmuje pełną szerokość okna (nie jest zawężana jak formularze), a pole
**🔎 Szukaj** filtruje listę po nazwie polecenia albo kombinacji.

Skróty są zdefiniowane w jednym rejestrze (`core/shortcuts.py`) i rejestrowane **dokładnie
raz**. Wcześniej te same kombinacje istniały równolegle jako skrót edytora i akcja menu —
Qt uznawało je za niejednoznaczne i **nie uruchamiało żadnej**, przez co `Ctrl+U` nie działał.

## Wyszukiwanie w wielu plikach

Wyszukiwanie przeszukuje wszystkie pliki projektu naraz — nie tylko ten, który akurat masz
otwarty. Dostępne na dwa sposoby, ten sam panel:

* **osobne okno** (`Ctrl+F`) — jak w OmegaT: niemodalne, **można mieć kilka naraz**
  (np. jedno dla `STAMP CARD`, drugie dla `System`), `Esc` zamyka, dwuklik na wyniku przenosi
  do segmentu, a okno zostaje otwarte obok. Opcje *Zawsze na wierzchu* i *Zamykaj po przejściu
  do segmentu*. Rozmiar okna jest zapamiętywany;
* **zakładka 🔍 Znajdź i zamień** — gdy wolisz wszystko w jednym oknie.

To, co robi `Ctrl+F`, ustawiasz w *Ustawienia → Ogólne → „Ctrl+F otwiera osobne okno
wyszukiwania (jak w OmegaT)”*. Domyślnie okno. Zakładka jest zawsze dostępna, a z niej
przycisk **🗗 Otwórz w osobnym oknie** przenosi bieżące wyszukiwanie do okna.

| Element | Opis |
|---|---|
| **Zakres** | *Cały projekt* • *Tylko przeglądany plik* • *Wybrane pliki…* (okno z listą i polami wyboru) |
| **Tryby** | zawiera • całe słowo • dokładne • regex |
| **Ignoruj znaczniki** | `\n`, `\p`, `<<KON>>` i twarde końce wiersza liczą się jak spacja — fraza `STAMP CARD System` znajdzie `STAMP CARD\nSystem` (domyślnie włączone) |
| **Ignoruj ogonki** | wpisujesz `zolw`, znajduje `żółw` |
| **Filtry** | tylko źródło / tylko tłumaczenie, tylko nieprzetłumaczone, tylko przetłumaczone, pomijanie wykluczonych |
| **Filtr statusu** | `○ nowy` • `✎ roboczy` • `✓ przetłumaczony` • `★ zatwierdzony` • `🚫 pominięty` — można zaznaczyć kilka naraz |
| **Wyniki** | drzewo: plik → segmenty, z licznikiem trafień i fragmentem z kontekstem `«szukana fraza»` |
| **Dodatkowo** | opcjonalnie przeszukuje też pamięć TM i glosariusz |
| **Zamiana** | *Zamień w zaznaczonych* (tylko wybrane wyniki) albo *Zamień wszystkie* (cały zakres) |
| **Szukanie w trakcie pisania** | wyniki od 2 znaków, z **adaptacyjnym opóźnieniem** (200 ms – 1,5 s zależnie od wielkości projektu) |

**Szukanie po samym statusie.** Nie musisz wpisywać frazy — zaznacz status (albo kilka)
i naciśnij *Szukaj*, a program wypisze wszystkie pasujące segmenty pogrupowane po plikach.
Tak znajdziesz np. wszystkie segmenty robocze do dokończenia albo sprawdzisz, co zostało
wykluczone. Fraza i status **działają razem** — zawężają wynik jednocześnie.

**Przejście do wyniku działa niezależnie od filtrów.** Trafienie może leżeć w pliku innym niż
aktualnie przeglądany albo być ukryte filtrem siatki lub statusu — program sam odsłania segment
(przełącza plik na liście, czyści filtr tekstu, ustawia status na *Wszystkie*) i pisze w pasku,
co zmienił. Wcześniej edytor pokazywał właściwy segment, ale siatka podświetlała inny wiersz.

**Podświetlanie:** po przejściu do segmentu (dwuklik, `Enter`, `F3`) trafienia są zaznaczone
na pomarańczowo w polu źródłowym i w tłumaczeniu — bieżące mocniejszym odcieniem.
Podświetlenie nie kasuje żółtego oznaczenia terminów glosariusza ani fioletowego oznaczenia wcięć.
`F3` / `Shift+F3` działają na **aktywnym oknie** wyszukiwania, więc przy kilku otwartych oknach
klawisz przechodzi po wynikach tego, z którego właśnie korzystasz.

Wydajność (20 000 segmentów, ~40 plików):

| Tryb | Czas |
|---|---:|
| zawiera, z ignorowaniem znaczników | **121 ms** |
| zawiera, bez ignorowania | **105 ms** |
| regex | **109 ms** |
| całe słowo | **138 ms** |

Zamiast przechodzić tekst znak po znaku (1,3 s) budowane jest jedno wyrażenie regularne
dopasowujące frazę wprost w oryginalnym tekście — pozycje trafień są od razu poprawne,
a całą pracę wykonuje silnik regex w C. Skompilowane wzorce są zapamiętywane w podręcznej pamięci.

## Szukanie spacji i białych znaków

*Znajdź i zamień → wiersz **␣ Białe znaki***

Spacja na początku wiersza w edytorze wygląda **identycznie** jak jej brak — a w plikach gier
zmienia wcięcie dialogu. Ten filtr znajduje to, czego nie widać:

| Filtr | Co znajduje |
|---|---|
| **␣ spacja na początku** | segment zaczyna się od spacji (również twardej `\u00a0`) |
| **spacja na końcu ␣** | segment kończy się spacją |
| **podwójna spacja** | dwie lub więcej spacji **wewnątrz** tekstu |
| **→ tabulator** | tabulator w tekście — łatwo pomylić ze spacjami |
| **≠ inne brzegi niż źródło** | tłumaczenie ma inne wcięcie niż oryginał |

**Działa bez wpisywania frazy** — wystarczy zaznaczyć pole wyboru. Można też połączyć
z frazą (wtedy wynik to trafienia frazy **tylko** w segmentach z danym problemem) oraz
z filtrem statusu i zakresem plików.

Wynik pokazuje, o który problem chodzi i podświetla dokładne miejsce:

```
segment 1   źródło   ␣ spacja na początku — « »Wciecie na poczatku dialogu.
segment 3   źródło   podwójna spacja — Ma«  »podwojna spacje w srodku.
segment 4   źródło   spacja na końcu ␣ — Konczy sie spacja« »
```

**Wcięcie nie jest mylone z podwójną spacją** — spacje na brzegach obsługuje osobny filtr,
więc `„  Ala ma kota”` zgłosi tylko „spacja na początku”. Tak samo liczy to kontrola jakości.

Pomiar: **78 ms** dla 20 000 segmentów, więc filtr można trzymać włączony na stałe.

## Spacje i wcięcia z pliku źródłowego

W plikach gier wiersz często zaczyna się spacją (wcięcie dialogu). SuperCAT **zachowuje ją**
i **wyraźnie pokazuje**:

* segmentacja nie obcina spacji ani tabulatorów na brzegach segmentu (tylko znaki końca wiersza),
* w siatce segmentów wcięcie oznacza znak `␣` — **bez kolorowych bloków i ramek**,
  żeby lista segmentów pozostała czytelna przy wybieraniu wiersza,
* **w polu źródła i tłumaczenia wcięcie ma kolorowe tło** — widać je nawet przy jednej spacji,
* gdy w źródle jest wcięcie, a w tłumaczeniu go **brakuje**, pierwszy znak tłumaczenia dostaje
  **czerwone tło z falowanym podkreśleniem** — od razu widać, że czegoś brakuje,
* przycisk **␣ Wcięcie** (albo `Ctrl+Shift+W`) nadaje tłumaczeniu spacje ze źródła,
* nad polem tłumaczenia widnieje informacja `␣ wcięcie: ␣1 z przodu`,
* każde tłumaczenie wstawione z TM, MT, AI lub dopasowania zdań **dziedziczy spacje źródła**,
* eksport odtwarza plik z tymi samymi wcięciami,
* QA zgłasza segment, w którym spacje na brzegach różnią się od źródła
  (kontrola *Spacje na brzegach*, można ją wyłączyć),
* podwójne spacje wewnątrz tekstu są nadal zgłaszane, ale wcięcie na początku wiersza — nie.

### Znaki specjalne — wszystko do wyłączenia

W *Ustawienia → Ogólne* są trzy niezależne przełączniki:

| Ustawienie | Działanie |
|---|---|
| **Pokazuj znaki spacji i tabulatora (`␣` `→`) na brzegach** | wyłączone → w tabeli jest zwykły tekst, bez żadnych symboli |
| **Pokazuj znak końca wiersza (`⏎`) w tabelach** | wyłączone → w miejscu `\n` pojawia się zwykła spacja |
| **Zestaw znaków specjalnych** | `␣ → ⏎` (standardowe) • `· » ¶` (dyskretne) • `▁ ▸ ↵` (wyraziste) • `_ > \n` (tylko ASCII, gdy czcionka nie ma symboli Unicode) |
| **Podświetlaj spacje na brzegach segmentu** | kolorowe tło wcięcia w polach edytora |

Zmiana działa **natychmiast** — siatka segmentów i otwarte okna wyszukiwania odświeżają się same,
bez restartu programu. Ustawienia obejmują siatkę segmentów oraz wyniki wyszukiwania (fragmenty
z kontekstem i podgląd wpisów TM).

Zachowywanie można wyłączyć w *Ustawieniach → Segmentacja → „Zachowuj spacje na początku
i końcu wiersza”* (wymaga ponownego wczytania plików: `F5`).

## Statystyki

Zakładka **✅ QA i statystyki** pokazuje zestawienie w czytelnych grupach, na dwóch kartach:

**📦 Projekt** — z nagłówkami sekcji:

| Grupa | Miary |
|---|---|
| **POSTĘP** | segmenty razem / przetłumaczone / pozostałe / zatwierdzone / robocze / pominięte, postęp % |
| **SŁOWA** | słowa w źródle, w tłumaczeniu, do przetłumaczenia |
| **ZNAKI** | **ze spacjami** i **bez spacji** — osobno dla źródła i tłumaczenia, plus znaki do przetłumaczenia |
| **ROZLICZENIE I DŁUGOŚĆ** | strony rozliczeniowe (1800 zn.), średnia długość segmentu, najdłuższy segment |
| **POZOSTAŁE** | segmenty powtórzone, znaczniki w źródle, wpisy w TM, liczba plików |

**📄 Pliki** — rozbicie na pliki: segmenty, przetłumaczone, postęp (kolorowany), słowa,
znaki ze spacjami i bez spacji.

Przycisk **📋 Kopiuj statystyki** przenosi całość do schowka — gotowe do wklejenia w wycenie.
Statystyki pojedynczego segmentu (panel w edytorze) też pokazują znaki bez spacji,
liczbę zdań, stosunek długości tłumaczenia do źródła oraz liczbę znaczników.

## Wydajność

Silnik TM został przepisany: indeks w pamięci (normalizacja wpisów raz, nie przy każdym
zapytaniu), wstępne filtrowanie kandydatów po długości i wspólnych tokenach, porównywanie
przez `rapidfuzz` (z zapasowym `difflib`, gdy biblioteki brak) oraz tryb wsadowy dla operacji
masowych. Pomiary (`python bench_tm.py`, TM 20 000 wpisów):

| Operacja | Przed | Po | Zysk |
|---|---:|---:|---:|
| Jedno wyszukanie dopasowań | 4770 ms | **32 ms** | **149×** |
| „Zastosuj TM” do 500 segmentów | ~34 min | **7,2 s** | **~280×** |
| Wyszukanie przy TM 5 000 wpisów | 1052 ms | **8 ms** | **131×** |

**Licznik czasu** — nad polem tłumaczenia widnieje pomiar ostatniego wyszukiwania:
`TM 224 ms • ZD 790 ms • ⏱ 1422 ms • TM: 10840` (dopasowania rozmyte, dopasowanie zdań, czas od
zmiany segmentu, rozmiar pamięci). **Kliknięcie kopiuje pomiar do schowka** (albo `Ctrl+Shift+P`)
wraz z numerem segmentu i jego długością – gotowe do wklejenia w zgłoszeniu.
Jednostki (ms / s / min / automatycznie) wybiera się w *Ustawieniach → Ogólne*.

**Przełącznik dopasowania zdań w trzech miejscach** — pole „Włącz dopasowanie zdań" wprost
w panelu, pozycja w menu *Widok* (`Ctrl+Shift+M`) oraz pełne ustawienia w *Ustawieniach →
Pamięć TM*. Wszystkie trzy są ze sobą zsynchronizowane.

**Natychmiastowa reakcja** — odstęp przed startem wyszukiwania jest **adaptacyjny**: startuje po
60 ms, a wydłuża się tylko wtedy, gdy poprzednie szukanie realnie trwało długo. Wcześniej sztywne
350 ms było głównym składnikiem odczuwanego opóźnienia (samo szukanie zajmowało ~7 ms).

| Czas od zmiany segmentu do wyników | Przed | Po |
|---|---:|---:|
| TM 10 800 jednostek (mediana) | 357 ms | **81 ms** |

**Rozgrzewka w tle** — indeksy pamięci budują się w osobnym wątku zaraz po otwarciu projektu,
więc pierwsze wyszukiwanie nie płaci jednorazowego kosztu w trakcie pracy.

**Szybkie usuwanie znaków diakrytycznych** — `str.translate` z gotową tablicą zamiast rozkładu
Unicode NFD (przy 10 tys. wpisów to były ~1,6 mln wywołań `unicodedata.category`).
Budowa indeksu: 381 ms → **210 ms**.

**Filtrowanie wektorowe** — długości wpisów trzymane są w tablicy `numpy`, więc odsiewanie
kandydatów to jedna operacja wektorowa zamiast pętli po całej pamięci.

**Wielordzeniowe wyszukiwanie** — wszystkie linie segmentu porównywane są **jednym**
wywołaniem `rapidfuzz.cdist`, które liczy macierz podobieństw na wielu rdzeniach i zwalnia GIL
na czas obliczeń (wcześniej każda linia szła osobno w pętli Pythona, blokując interfejs).
Najlepszych kandydatów wybiera `numpy.argpartition`, bez sortowania całej macierzy.

**Indeks słów** — zamiast przeglądać całą pamięć przy każdym wyszukiwaniu, program bierze tylko
wpisy dzielące słowo z segmentem. Pierwszeństwo mają słowa najrzadsze; pospolite (występujące
niemal wszędzie) są pomijane, bo nic nie zawężają. W typowych danych ogranicza to przegląd
z tysięcy wpisów do kilkunastu.

| Dopasowanie zdań | Przed | Po |
|---|---:|---:|
| TM 10 800 jednostek | 80,6 ms | **8,3 ms** |
| TM 30 000 | — | **20,6 ms** |
| TM 60 000 | — | **45,8 ms** |

**Zapis pamięci do TMX** — baza SQLite jest formatem **roboczym** (szybkie wyszukiwanie
rozmyte), ale przy każdym zapisie projektu (`Ctrl+S`) pamięć jest dodatkowo zrzucana do
`tm/project_tm.tmx` — formatu wymiennego, który otworzysz w innym narzędziu CAT. Opcję można
wyłączyć w *Ustawieniach → Pamięć TM*, jest też pozycja w menu Narzędzia.

**Pliki TMX wczytywane tylko raz** — program zapamiętuje rozmiar i czas modyfikacji każdego
zaimportowanego pliku (tabela `tm_files`). Niezmienione pamięci nie są wczytywane ponownie
przy kolejnym otwarciu projektu.

**Odroczony zapis** — zatwierdzenie segmentu (`Ctrl+Enter`) nie synchronizuje dysku po każdym
wpisie; zmiany są zapisywane najwyżej raz na sekundę oraz zawsze przy `Ctrl+S` i zamykaniu.
Tabela pamięci nie jest też przebudowywana, gdy jej zakładka pozostaje niewidoczna.

**Płynność interfejsu** — długie pętle Pythona blokowały GIL i zacinały okno nawet na 433 ms.
Teraz budowa indeksu, budowa cache linii, filtrowanie kandydatów i wywołania `rapidfuzz`
wykonują się **porcjami**, oddając GIL między nimi; blokada indeksu jest zwalniana co porcję,
a indeks powstaje przy otwarciu projektu, nie przy pierwszym wyszukiwaniu.

| Zacięcie interfejsu | Przed | Po |
|---|---:|---:|
| TM 10 800 jednostek (2 pliki TMX), praca w edytorze | 60 ms | **16 ms** |
| jw. z **włączonym** dopasowaniem zdań | — | **18 ms** |
| TM 60 000 wpisów, ustawienia domyślne | — | **26 ms** |
| TM 60 000 z włączonym dopasowaniem zdań | 433 ms | **~120 ms jednorazowo** |

**Wyniki poprzedniego segmentu** — panele podpowiedzi są czyszczone natychmiast po przejściu
do kolejnego segmentu i pokazują stan „⏳ Szukanie…”, więc stare dopasowania nie wyglądają już
jak podpowiedzi bieżącego segmentu. Spóźnione wyniki z porzuconego wyszukiwania są odrzucane.

**Zabezpieczenia dopasowania zdań** — funkcja jest domyślnie wyłączona, a po włączeniu chroni ją
kilka mechanizmów: wyszukiwanie jest **przerywane** natychmiast, gdy przejdziesz do kolejnego
segmentu (2256 ms → 55 ms), pomijane powyżej ustawionego rozmiaru pamięci (domyślnie 20 000
jednostek) i uruchamiane w wątku roboczym. W ustawieniach można też włączyć automatyczne
wstawianie najlepszego złożenia (również po wczytaniu pliku) oraz podpowiedzi z segmentów
przetłumaczonych w projekcie — obie opcje domyślnie wyłączone, bo zwiększają obciążenie.

| Dopasowanie zdań | Przed | Po |
|---|---:|---:|
| TM 5 000 wpisów | 1479 ms | **7 ms** |
| TM 20 000 wpisów | — | **38 ms** |
| Porzucone wyszukiwanie (80 000 wpisów) | 2256 ms | **55 ms** |

**Stabilność przy pracy w tle** — indeks pamięci jest chroniony blokadą (`RLock`), bo czyta go
wątek roboczy, a modyfikuje wątek interfejsu; bez tego dochodziło do wyścigu i zawieszenia
programu. Cache linii dla dopasowania zdań budowany jest **przyrostowo**, znormalizowane teksty
liczone są raz przy dodaniu wpisu, a segmenty przetłumaczone w sesji trafiają do pamięci
„w locie” tylko wtedy, gdy faktycznie się zmieniły.

**Praca w tle** — długie operacje działają w osobnych wątkach (`ui/workers.py`), więc okno
nie zamarza i można je przerwać przyciskiem „Anuluj”:

* wyszukiwanie dopasowań dla bieżącego segmentu (wyniki spóźnione są odrzucane, gdy
  użytkownik zdążył przejść dalej),
* „Zastosuj TM” do całego projektu — automatyczne uzupełnianie tłumaczeń z pamięci,
* tłumaczenie maszynowe wszystkich segmentów,
* import dużych plików TMX (parsowanie strumieniowe `iterparse`, stałe zużycie pamięci).

Baza SQLite korzysta z trybu WAL i powiększonego cache'u.

## Nawigacja strzałkami

**Zwykłe `↑` / `↓` przechodzą między segmentami** — nie trzeba trzymać `Ctrl`.

W polu tłumaczenia działa to rozsądnie: dopóki tekst ma kilka linii, strzałki poruszają
kursorem po liniach, a **dopiero z pierwszej/ostatniej linii „wychodzą” do sąsiedniego
segmentu** (tak jak w OmegaT). Zaznaczony tekst ma pierwszeństwo — wtedy strzałka nie
zmienia segmentu. Można to wyłączyć: *Ustawienia → Ogólne → „Strzałki ↑/↓ w polu
tłumaczenia przechodzą między segmentami”*.

**Naprawione: `Ctrl+↑/↓` kumulowało zaznaczenie.** Przy każdym przejściu do kolejnego
segmentu poprzedni wiersz **zostawał zaznaczony** — po kilku naciśnięciach podświetlona
była połowa projektu, a operacje grupowe (zmiana statusu, pomijanie) działały na wszystkich
tych wierszach naraz.

Przyczyna nie leżała w obsłudze klawiszy, tylko w `QTableWidget.selectRow()`: w trybie
zaznaczania wielu wierszy metoda ta **dokłada** wiersz zamiast zastąpić zaznaczenie.
Ten sam błąd występował przy zmianie segmentu myszą i z menu. Teraz wiersz wybierany jest
wprost przez model z flagą `ClearAndSelect`.

`Shift+↑/↓` nadal zaznacza zakres — grupowe operacje działają bez zmian.

## Skróty klawiszowe

| Skrót | Działanie |
|---|---|
| `Ctrl+N` / `Ctrl+O` / `Ctrl+S` | nowy / otwórz / zapisz projekt |
| `Ctrl+I` / `Ctrl+E` | importuj pliki / eksportuj tłumaczenia |
| `Ctrl+Enter` | zatwierdź segment, zapisz do TM i przejdź dalej |
| `Ctrl+↑` / `Ctrl+↓` | poprzedni / następny segment (działa też podczas pisania) |
| `Alt+↑` / `Alt+↓` | poprzedni / następny segment |
| `Ctrl+PgUp` / `Ctrl+PgDn` | poprzedni / następny segment |
| `Ctrl+Home` / `Ctrl+End` | pierwszy / ostatni segment |
| `↑` / `↓` | przechodzenie po segmentach — w siatce zawsze, w polu tłumaczenia na skraju tekstu |
| `Shift+↑` / `Shift+↓` w siatce | zaznaczanie zakresu segmentów (operacje grupowe) |
| `Ctrl+D` | kopiuj źródło do tłumaczenia |
| `Ctrl+Spacja` | wstaw najlepsze dopasowanie z TM |
| `Ctrl+M` | tłumaczenie maszynowe segmentu |
| `Ctrl+Shift+Q` | ⚡ QuickTrans – porównanie wielu silników |
| `Ctrl+Shift+X` | 📝 Edytor pamięci TM / TMX |
| `Ctrl+Shift+M` | 🔗 Włącz/wyłącz dopasowanie zdań |
| `Ctrl+Shift+P` | 📋 Kopiuj pomiar czasu do schowka |
| `Ctrl+Shift+S` | zapisz segment do TM |
| `Ctrl+F` | znajdź i zamień — osobne okno albo zakładka (do wyboru w Ustawieniach) |
| `Ctrl+Shift+N` | nowe okno wyszukiwania (można mieć kilka naraz) |
| `Esc` | zamknij okno wyszukiwania |
| `Ctrl+Shift+W` | nadaj tłumaczeniu wcięcie ze źródła |
| `Ctrl+Shift+J` | sprawdź poprawność języka w tłumaczeniu |
| `Ctrl+Z` / `Ctrl+Y` | cofnij / ponów — tekst **oraz oznaczenia** |
| `Ctrl+Shift+I` / `Ctrl+Shift+R` | pomiń / przywróć zaznaczone segmenty |
| `Ctrl+U` / `Ctrl+Shift+U` | następny / poprzedni nieprzetłumaczony segment |
| `Ctrl+Shift+Y` / `Ctrl+Shift+A` | następny przetłumaczony / niezatwierdzony |
| prawy przycisk w polu tłumaczenia | propozycje poprawek, dodanie wyrazu do słownika |
| `Ctrl+Shift+F` | szukaj zaznaczonego wyrazu w całym projekcie |
| `Ctrl+Shift+E` | szukaj zaznaczonego wyrazu tylko w bieżącym pliku |
| `F3` / `Shift+F3` | następny / poprzedni wynik wyszukiwania |
| `F5` / `F8` / `F9` / `F1` | przeładuj source/ / QA / statystyki / pomoc |
| `Ctrl+T` / `Ctrl++` / `Ctrl+-` | motyw / większa / mniejsza czcionka |

## Silniki tłumaczenia — co robić przy błędach

**Silnik lokalny** (offline) nie jest już zaślepką z 25 hasłami. Buduje słownik z:

1. **glosariusza projektu** — terminy, które sam dodałeś,
2. **pamięci TM** — krótkie wpisy (do 40 znaków) traktowane jak terminologia,
3. wbudowanej listy podstawowych słów.

Gdy nie zna wyrazu, mówi to wprost: *„[MT lokalne: brak w słowniku (25 haseł) — dodaj termin
do glosariusza]”* zamiast oddawać nietknięty oryginał udający tłumaczenie.

**Google (bez klucza)** ma limit zapytań liczony na adres IP — po kilkunastu wywołaniach pod
rząd zwraca `429 Too Many Requests`. Program automatycznie próbuje wtedy **drugiego punktu
dostępowego Google**, rozliczanego osobno; w praktyce tłumaczenie idzie dalej bez przerwy.
Dopiero gdy oba odmówią, pojawia się komunikat z podpowiedzią, żeby odczekać albo użyć MyMemory.

**LibreTranslate** działa **na Twoim komputerze** — bez limitów i bez wysyłania tekstu
w internet. Nie trzeba już nic konfigurować ręcznie: w *Ustawienia → 🤖 Tłumaczenie maszynowe*
jest sekcja **🖥️ LibreTranslate — własny silnik na tym komputerze**:

| Przycisk | Działanie |
|---|---|
| **⬇ Zainstaluj LibreTranslate** | uruchamia `pip install libretranslate` w tle, z **paskiem postępu i licznikiem MB** |
| **▶ Uruchom serwer** | startuje serwer i czeka, aż odpowie; pasek pokazuje, **ile modeli już pobrano** |
| **⏹ Zatrzymaj** | zamyka serwer uruchomiony przez program |
| **🔌 Sprawdź** | pełna diagnoza w osobnym oknie (patrz niżej) |

**🔌 Sprawdź** nie tylko odświeża etykietę — otwiera okno z pełnym stanem, więc od razu widać,
czy kliknięcie coś dało:

```
Pakiet: 1.9.6
Najnowsza wersja: 1.9.6 (masz aktualną)
Pobrane modele: en, pl
Miejsce na dysku: 162 MB
Katalog modeli: C:\Users\…\argos-translate
Serwer: ⏸️ nie odpowiada pod http://127.0.0.1:5000
```

Gdy serwer działa, dochodzi lista języków, które faktycznie udostępnia. Jeśli występuje znane
ostrzeżenie `RequestsDependencyWarning`, okno dopisuje wyjaśnienie i polecenie naprawcze.

### Wybór języków z listy

Zamiast wpisywać kody z pamięci (i trafiać na błąd *„Unavailable language codes”*) wybierasz je
z **listy 50 języków** pobranej z repozytorium:

* **✅ zielony** — modele już są na dysku, **⬇** — trzeba je pobrać;
* przy każdym języku liczba par tłumaczeniowych (`English (en) — 98 par`, `Polish (pl) — 2 pary`);
* pole **szukaj języka…** zawęża listę, **↻ Odśwież listę** pobiera aktualny spis,
  **✅ Tylko pobrane** zaznacza to, co już masz;
* pod listą podsumowanie: *„Wybrano 2: en, pl • już pobrane: en, pl • wszystko już jest na dysku”*
  albo szacowana waga tego, co zostanie dociągnięte.

Lista i pole tekstowe są zsynchronizowane w obie strony — możesz nadal wpisać kody ręcznie.

**Ile to waży** (zmierzone, nie szacowane):

| Element | Waga |
|---|---|
| pakiet `libretranslate` | **1,1 MB** (z zależnościami zwykle 200–400 MB) |
| modele jednej pary językowej (`en,pl`) | **163 MB** |
| pełny zestaw wszystkich języków | ok. **4 GB** |

Pasek instalacji czyta wiersze pipa i pokazuje `Pobieranie: 5.2/12.3 MB (42%)`, a przy starcie
serwera — **`Modele: 42 MB / 133 MB (31%)`**, z podglądem pojedynczego pliku pod spodem
(`Model 1/2 (en → pl): 42 MB / 64 MB`). Stan pakietu
podaje wersję i **sam sprawdza w PyPI, czy jest najnowsza**: *„Pakiet zainstalowany
(wersja 1.9.6 — najnowsza), serwer nie jest uruchomiony • modele: 163 MB”*.

**Naprawione błędy uruchamiania (zgłoszone i potwierdzone pomiarem):**

* *„No module named libretranslate.\_\_main\_\_; libretranslate is a package and cannot be
  directly executed”* — pakiet **nie ma** pliku `__main__.py`, więc `python -m libretranslate`
  nigdy nie zadziała. Program używa teraz skryptu konsolowego `libretranslate` tworzonego przez
  pipa (szuka go też obok interpretera, w `Scripts/`), a gdyby go nie było — modułu
  `libretranslate.main`. Zweryfikowane: serwer wstaje, tłumaczy (`You received the STAMP CARD!`
  → `Otrzymaliście kartę STAMP!`) i zatrzymuje się poprawnie.
* *„RequestsDependencyWarning: urllib3 (2.7.0) or chardet (7.4.3)/charset_normalizer (3.4.7)
  doesn't match a supported version!”* — **to nie jest błąd i nic nie psuje.** Biblioteka
  `requests` przy starcie porównuje wersje swoich zależności z tymi, pod które była budowana:
  deklaruje `chardet <6`, a w systemie jest `chardet 7.x`, więc wypisuje ostrzeżenie —
  i działa dalej normalnie (sprawdzone zapytaniem HTTP: `200 OK`). Serwer uruchamiany przez
  program dostaje `PYTHONWARNINGS`, więc komunikat nie zaśmieca dziennika, a w Ustawieniach
  jest krótkie wyjaśnienie. Kto chce usunąć go u źródła:

  ```bash
  pip install -U requests     # albo:  pip uninstall chardet
  ```
* **`IndexError: list index out of range` w `create_app` (Windows)** — najgroźniejszy z tych
  błędów, bo objaw jest zupełnie gdzie indziej niż przyczyna. Pełna kaskada:

  1. Modele nazywają się **`English → Polish`** — ze strzałką `→` (U+2192).
  2. Konsola Windows pracuje w **cp1250**, która tego znaku nie zna, więc `print` z nazwą
     modelu wyrzuca `UnicodeEncodeError: 'charmap' codec can't encode character '\u2192'`.
  3. LibreTranslate łapie ten wyjątek i wypisuje mylące
     *„Cannot update models (normal if you're offline)”* — **choć internet działa**.
  4. Modele nie zostają zainstalowane, więc lista języków jest pusta.
  5. `create_app` robi `languages[1]` na pustej liście → `IndexError` → serwer pada.

  Naprawione dwutorowo: podproces dostaje **`PYTHONIOENCODING=utf-8` i `PYTHONUTF8=1`**
  (strzałka wypisuje się poprawnie na każdej konsoli), a **modele pobierane są w programie,
  jeszcze przed startem serwera** — dzięki temu widać prawdziwy błąd zamiast „normal if you're
  offline”, a serwer nigdy nie startuje na pustej liście języków. Komunikaty są tłumaczone na
  ludzki język: zamiast `IndexError` pojawia się *„Serwer wystartował bez modeli językowych…
  Przyczyna: konsola Windows nie potrafiła wypisać nazwy modelu «English → Polish»”*.
  Rozpoznawany jest też zajęty port 5000.
* **Pasek pobierania stał w miejscu i nie pokazywał megabajtów** — bo argos-translate
  ściąga model **w całości do pamięci** (`networking.get()`) i zapisuje jednym `write`
  dopiero na końcu. Katalog modeli nie rósł w trakcie, więc licznik obserwujący dysk
  przez kilka minut pokazywał zero, a potem od razu komplet. Program pobiera teraz modele
  **sam, kawałkami po 256 kB**, i dopiero gotowy plik oddaje argosowi do instalacji.
  Rozmiar całości bierze z nagłówka `Content-Length` (para `en,pl` to **133 MB**: 64 MB
  `en→pl` + 68 MB `pl→en`), plik leci najpierw jako `.part`, a pobieranie da się przerwać.
* **Pasek postępu się nie pokazywał** — pole `lt_progress` istniało **dwa razy**: raz dla
  LanguageTool (zakładka *Pisownia i język*), raz dla LibreTranslate. Obie zakładki to jeden
  obiekt, więc drugie przypisanie nadpisywało pierwsze i postęp sterował niewidocznym paskiem
  z innej zakładki. Pasek LibreTranslate nazywa się teraz `ltr_progress`; test regresji pilnuje,
  że to dwa osobne widżety.

Pole **Języki do pobrania** (domyślnie `en,pl`) ogranicza modele do pary językowej projektu —
pełny zestaw to ok. 4 GB, jedna para to 163 MB i pobiera się znacznie szybciej. Po udanym starcie adres
serwera wpisuje się sam w ustawieniach silnika. Serwer jest zamykany przy wyjściu z programu.

Gdy serwera brak, komunikat mówi wprost, co zrobić, zamiast pokazywać `WinError 10061`.

**Microsoft Translator (bez klucza API)** — działa **od razu, bez konta i bez klucza**.
Program podszywa się pod przeglądarkę: pobiera ze strony `bing.com/translator` jednorazowy
token i wysyła zapytanie tak, jak zrobiłaby to strona WWW. To **ten sam model neuronowy**,
który stoi za płatnym Azure Translator, więc jakość jest wyraźnie wyższa niż w MyMemory:

| Źródło | MyMemory | Microsoft (bez klucza) |
|---|---|---|
| `WIRELESS COMMUNICATION` | Komunikacja bezprzewodowa | **ŁĄCZNOŚĆ BEZPRZEWODOWA** |
| `Thank you for using the MYSTERY\nGIFT System.` | — | `Dziękujemy za korzystanie z\nsystemu MYSTERY GIFT.` |
| `Would you like to save the game?` | — | `Czy chciałbyś zapisać grę?` |

Token żyje około godziny i jest **zapamiętywany w pamięci programu** — jedno pobranie strony
(ok. 600 kB) obsługuje setki segmentów. Dostęp jest chroniony blokadą, więc równoległe
zapytania QuickTrans i „Tłumacz wszystko” nie pobierają strony po kilka razy. Gdy token
wygaśnie w trakcie pracy, program odświeża go sam i ponawia zapytanie. Przy zbyt wielu
zapytaniach z jednego adresu IP pojawia się czytelny komunikat o limicie.

**Azure Translator (z kluczem)** — oficjalne API Microsoftu ma **najhojniejszą warstwę darmową
ze wszystkich dostawców: 2 000 000 znaków miesięcznie** (plan **F0**), czterokrotnie więcej
niż DeepL API Free i Google Cloud Translation (po 500 000). Wymaga jednak konta Azure
i utworzenia zasobu *Translator*; po wyczerpaniu limitu API po prostu przestaje odpowiadać
(błąd 429/403) — **nie nalicza opłat**. W *Ustawieniach → Tłumaczenie maszynowe* są trzy pola:
**klucz**, **region zasobu** (np. `westeurope`) i **endpoint**. Komunikaty błędów są
rozpoznawane: zły klucz, brak regionu, wyczerpany limit F0.

> Nie chcesz zakładać konta Azure? Wybierz **Microsoft Translator / Bing (bez klucza API)** —
> ten sam model, zero konfiguracji. Azure ma sens, gdy potrzebujesz gwarancji limitu
> i stabilnego API do dużych wsadów.

**DeepL przez stronę (bez klucza)** — silnik `DeepL przez stronę` korzysta z tego samego
wewnętrznego punktu, do którego strzela **przeglądarka na deepl.com**. Nie potrzebuje konta
ani klucza i daje jakość prawdziwego DeepL:

| Źródło | DeepL przez stronę |
|---|---|
| `{PLAYER} obtained a POTION.` | `{PLAYER} otrzymał Eliksir.` |
| `Thank you for using the MYSTERY\nGIFT System.` | `Dziękujemy za skorzystanie z\nsystemu MYSTERY GIFT.` |
| `Press the A button to continue.` | `Naciśnij przycisk A, aby kontynuować.` |

**To droga nieoficjalna** — program udaje przeglądarkę, więc DeepL może ją w każdej chwili
zamknąć, a limit zapytań na adres IP jest **bardzo ostry**. Pomiar: z 8 pojedynczych zapytań
pod rząd przeszło 6, potem `429`; przy odstępie 5 s przechodzi 5 na 6. Na łączach
współdzielonych (firma, akademik, VPN, CGNAT) blokada potrafi wystąpić **przy pierwszym
kliknięciu** — bo limit liczony jest dla całego adresu IP, nie dla Ciebie. Zmierzone:
po odmowie blokada trzymała dłużej niż 90 s.

**Naprawione: jeden segment = jedno zapytanie.** Wcześniej segment z plików gier był
dzielony po `\n` i `\p` na 2–4 kawałki, a każdy szedł jako osobne zapytanie — limit padał,
zanim użytkownik zdążył cokolwiek zrobić. Teraz DeepL dostaje **cały segment naraz**
(jak modele AI), więc zapytań jest kilkukrotnie mniej.

**Zapas zamiast błędu.** Gdy DeepL odmówi, program nie zwraca już komunikatu o błędzie —
tłumaczy tym samym segmentem przez **Microsoft (bez klucza)** i pisze o tym w pasku
informacji: *„DeepL przez stronę jest zablokowany (limit zapytań) — użyto silnika Microsoft”*.
Dzięki temu „Tłumacz wszystko” nie zatrzymuje się na pierwszej paczce. Zachowanie można
wyłączyć w *Ustawieniach → Tłumaczenie maszynowe* („gdy limit wyczerpany, tłumacz
Microsoftem”), jeśli wolisz zobaczyć surowy błąd. Blokada jest zapamiętywana, więc program
nie zasypuje serwera zapytaniami i od razu podaje, ile trzeba odczekać.

Rozwiązaniem jest **tłumaczenie paczkami**: wewnętrzne API przyjmuje kilkanaście tekstów
w jednym zapytaniu — **10 segmentów w 0,8 s**. Dlatego „Tłumacz wszystko” wysyła segmenty
dziesiątkami i limitu nie łapie, a odstęp między zapytaniami jest pilnowany globalnie
(również dla równoległych wątków QuickTrans). Gdy paczka mimo wszystko przepadnie, pozostałe
segmenty nie giną — błąd trafia tylko do tych dziesięciu.

Do pojedynczych segmentów w Edytorze silnik nadaje się bardzo dobrze; do tłumaczenia całych
dużych plików pewniejszy jest **Microsoft (bez klucza)** albo **darmowy plan DeepL API Free:
500 000 znaków miesięcznie**, bez karty płatniczej —
[deepl.com/pro-api](https://www.deepl.com/pro-api), klucz wkleja się w Ustawieniach.

> **Oficjalne API DeepL bez klucza nie istnieje.** Sprawdzone i zablokowane:
> `api-free.deepl.com` → `403`, `deeplx.vercel.app` → `451 Unavailable For Legal Reasons`.
> Działa wyłącznie punkt używany przez samą stronę.

**Darmowe AI bez klucza** — sprawdziłem też, czy da się podpiąć czat AI „jak ze strony”:
Pollinations (`402 Payment Required`), DuckDuckGo AI Chat (`418` + obfuskowany challenge
wymagający JavaScriptu), api.airforce (`402`), OpenRouter i Puter bez tokenu (`401`).
**Żadna z tych dróg nie działa bez rejestracji.** Darmowe AI do tłumaczenia jest dostępne
tylko z bezpłatnym kluczem: **Google Gemini** (aistudio.google.com/apikey, bez karty)
albo **Puter AI** (bezpłatne konto).

W oknie **⚡ QuickTrans** błędy są tłumaczone na zrozumiały język (`⚠️ limit zapytań
wyczerpany – odczekaj kilka minut`), pełna treść jest pod kursorem, a przycisk
**🔁 Ponów nieudane** próbuje jeszcze raz **tylko tymi silnikami, które zawiodły**.
Zaznaczany jest pierwszy **działający** wynik, nie wiersz z błędem.

## Okno postępu przy wczytywaniu

Otwarcie projektu to kilka etapów, a przy większych zestawach plików trwa na tyle długo,
że bez informacji zwrotnej wygląda, jakby program zamarł (pomiar: **862 ms** dla 4 800
segmentów i pamięci 8 000 jednostek, z czego samo parsowanie plików to 650 ms).

Podczas otwierania — również z listy **📂 Ostatnie projekty** — pojawia się małe okno
z paskiem postępu i nazwą bieżącego etapu:

1. Wczytywanie projektu
2. Pamięć tłumaczeń — z liczbą jednostek
3. Glosariusz i słowniki — z liczbą terminów i słów
4. Parsowanie plików źródłowych — **z nazwą przetwarzanego pliku** (`plik 4/12: miasto.txt`)
5. Wczytywanie tłumaczeń
6. Kończenie

Okno jest modalne i bez przycisku zamknięcia, więc nie da się kliknąć w połowie pracy;
`Esc` też nic nie zrobi. Znika samo po zakończeniu — także gdy wystąpi błąd, żeby nie
zasłonić komunikatu. To samo okno pokazuje się przy przeładowaniu plików (`F5`).

## Pierwsze kroki

1. **Plik → Nowy projekt** (`Ctrl+N`) — podaj nazwę i parę językową.
2. **Importuj pliki** (`Ctrl+I`) — pliki trafią do `source/` i zostaną podzielone na segmenty.
3. Tłumacz w zakładce **Edytor**; `Ctrl+Enter` zatwierdza segment i zapisuje go do TM.
4. **QA** (`F8`) — sprawdź jakość przed oddaniem.
5. **Eksportuj** (`Ctrl+E`) — gotowe pliki znajdziesz w `target/`.

## Testy

```bash
python test_supercat.py
```

688 testów: segmentacja, projekty, parsery wszystkich formatów, tagi, TM z TMX, dopasowanie
zdań (także pliki ze znacznikami `\n` / `\p`), tryb wsadowy, progi wydajności, silniki MT
bez klucza API, QuickTrans, rozbicie wpisów TM na linie, kontrast motywu jasnego, automatyka
po wczytaniu, ochrona znaczników w MT, tłumaczenie linia po linii, rozmyte dopasowanie linii,
edycja TM w tabeli, edytor TMX, wydajność dopasowania zdań, równoległy dostęp z 4 wątków,
rejestr zaimportowanych pamięci, przerywanie wyszukiwania, limit rozmiaru TM, brak wpisów widmo
po wyczyszczeniu pamięci, czyszczenie paneli przy zmianie segmentu, zapis pamięci do TMX, pomijanie ponownego importu,
odroczony commit, indeks słów, adaptacyjne opóźnienie, szybkie usuwanie diakrytyków,
dostępność rapidfuzz/numpy, odsiewanie jednowyrazowych dopasowań, odrzucanie wpisów nieprzetłumaczonych,
złożenie całego segmentu, formatowanie i kopiowanie pomiaru czasu, integracja z Puter AI i Google Gemini, licznik zużycia z limitami, automatyczny fallback modelu Gemini, oczyszczanie odpowiedzi AI, panel pracy AI, kontekst całego segmentu dla AI,
odzyskiwanie zgubionych znaczników, scalanie zdań przełamanych znacznikiem, przeciąganie plików, nawigacja klawiaturą po segmentach, operacje na pojedynczym pliku, usuwanie plików,
wyszukiwanie w wielu plikach (zakresy, tryby, ignorowanie znaczników i ogonków, błędny regex, przejście do segmentu, podświetlanie trafień, zamiana),
zachowywanie wcięć z pliku źródłowego (segmentacja, dziedziczenie spacji przez tłumaczenie, eksport, kontrola QA),
okno wyszukiwania w stylu OmegaT (kilka okien naraz, przełącznik okno/zakładka, przejście do segmentu),
przejście do wyniku ukrytego filtrem pliku / tekstu / statusu (zgodność siatki z edytorem, także z zakładki QA),
podświetlanie wcięć w edytorze i w siatce (także ostrzeżenie o braku wcięcia, przywracanie wcięcia, wyłączanie opcji),
znaki specjalne ␣ → ⏎ (niezależne przełączniki spacji i końca wiersza, cztery zestawy znaków, natychmiastowe odświeżanie widoków),
kontrola poprawności języka w tłumaczeniu (odmiana po liczebnikach, zgodność zaimka z czasownikiem, interpunkcja, powtórzenia, typowe błędy, pomijanie znaczników gier, próg wielkości słownika, automatyczne poprawki),
zarządzanie słownikami (dodawanie z pliku, usuwanie, liczniki słów, podpowiedzi pisowni, lista słowników do pobrania),
wykrywanie kodowania słowników ISO-8859-2/UTF-8 z pliku .aff i z treści (polskie znaki bez „�”),
słownik SJP.pl z pełną odmianą (rozpakowywanie ZIP, formy po przecinku, pomijanie README, aktualizowany adres),
reguły segmentacji (własne skróty, wielka litera po kropce, liczby, dzielenie po znacznikach, scalanie krótkich, kropka przed nową linią), podgląd segmentacji na żywo,
rozbudowane statystyki (znaki ze spacjami i bez, strony rozliczeniowe, powtórzenia, znaczniki, rozbicie na pliki, kopiowanie do schowka),
wyłączniki pamięci TM (podpowiedzi, zapis przy zatwierdzeniu, nadpisywanie tłumaczenia),
rozdzielone sekcje LanguageTool offline i online (osobne włączniki i testy, pobieranie i usuwanie silnika, wzajemne wykluczanie trybów),
wykrywanie Javy poza PATH (JAVA_HOME, katalogi instalacyjne, wybór najnowszej, własna ścieżka, dobór wersji silnika do Javy),
rzeczywisty postęp pobierania silnika w procentach i megabajtach (podstawiony licznik tqdm, ograniczanie liczby zdarzeń),
liczniki postępu przy plikach odświeżane po każdej zmianie (także masowej), wykluczanie segmentów technicznych
(sześć sposobów dopasowania, reguły per plik, podgląd trafień, gotowe wzorce, zapis w projekcie, ochrona ręcznych decyzji),
nierozbijanie nagłówków <<< FILE: … >>> przez segmentację,
pomijanie wykluczonych segmentów w licznikach i pasku postępu, grupowe zaznaczanie i pomijanie segmentów
(zaznaczenie wielokrotne, odwracanie, pomijanie po wzorcu z zapisem reguły, ochrona ręcznych decyzji przed regułami),
dwukierunkowe cofanie wykluczeń (grupowe przywracanie, trwałość decyzji po F5, kasowanie ręcznych wyjątków),
grupowe oznaczanie statusów (nowy / roboczy / przetłumaczony / zatwierdzony na wielu segmentach naraz),
konfigurowalne skróty klawiszowe (rejestr bez duplikatów, edycja w Ustawieniach, wykrywanie konfliktów, przeładowanie bez restartu, filtrowanie i pełna szerokość tabeli),
skoki nawigacyjne ograniczone do przeglądanego pliku (z pytaniem przed wyjściem poza niego),
cofanie i ponawianie zmian oznaczeń oraz pominięć (Ctrl+Z / Ctrl+Y z klawiatury, także z pola tłumaczenia i dla operacji grupowych),
wyszukiwanie po statusie segmentu (pięć statusów, kilka naraz, szukanie bez frazy, łączenie z frazą, pomijanie wykluczonych),
okno postępu przy wczytywaniu projektu (etapy, nazwa parsowanego pliku, zamykanie po błędzie, modalność),
silnik lokalny oparty na glosariuszu i pamięci TM (pomijanie długich wpisów, komunikat o braku terminu),
zapasowy punkt dostępowy Google przy limicie 429, czytelne komunikaty błędów MT i ponawianie nieudanych silników w QuickTrans,
instalacja i uruchamianie własnego serwera LibreTranslate z poziomu programu (wykrywanie pakietu, wybór języków, bezpieczne zatrzymywanie),
czytelny komunikat DeepL o wymaganym kluczu z darmowym planem,
„Zatwierdź i dalej” zmieniające oznaczenie i skaczące do segmentu do zrobienia, oznaczenie „przetłumaczony” liczone w postępie,
zatwierdzony jako segment wykonany w licznikach, nawigacja w stylu OmegaT (Ctrl+U, Ctrl+Shift+U, Ctrl+Shift+Y, Ctrl+Shift+A z zawijaniem i omijaniem pominiętych),
podkreślanie błędów w polu tłumaczenia (czerwona falka dla literówek), menu podręczne z propozycjami i podmianą wyrazu,
dwuetapowe liczenie propozycji (szybkie od razu, dokładne w tle), dodawanie wyrazu do słownika użytkownika,
główny wyłącznik i szczegółowe przełączniki kontroli języka,
porządkowanie wyniku MT bez gubienia znaczników oraz reguły odmiany w poleceniu dla AI,
odporność `size()` na równoległy zapis, glosariusz, QA, eksport oraz pełny przepływ pracy w GUI
(wpisanie tłumaczenia → zatwierdzenie → zapis → ponowne otwarcie projektu). Wszystkie przechodzą.

Są też testy na obie rzeczy naprawione w tej wersji: **przeciąganie kolumn siatki**
(każda kolumna, także ostatnia; szerokości zapisane i przywrócone; menu nagłówka) oraz
**przełączanie układu prawego panelu** — prawa kolumna zachowuje szerokość, a panele po
zmianie są widoczne („wszystko naraz” ⇄ „zakładki”, wielokrotnie). Do tego testy
**przeciągania wysokości paneli**, **„Zastosuj TM ponownie”** (podmiana istniejącego
tłumaczenia, ochrona zatwierdzonych, uzupełnianie pustych), **czcionek** (panel i cały
interfejs) oraz **dopasowania zdań ze znacznikami** (`<<kon>>` nie ginie, brak
duplikatów, ostrzeżenie o resztkach tekstu źródłowego).

Benchmark wydajności TM:

```bash
python bench_tm.py
```

## Struktura kodu

```
SuperCAT.py              # uruchamianie
supercat/
├── app.py               # inicjalizacja Qt
├── core/                # logika niezależna od GUI
│   ├── settings.py      fileparser.py   tm.py
│   ├── project.py       glossary.py     mt.py
│   ├── segmentation.py  tags.py         qa.py
│   ├── exclusions.py    # reguły wykluczania segmentów technicznych
│   ├── langcheck.py     # kontrola języka: reguły offline + LanguageTool
│   ├── libretranslate_setup.py  # instalacja i serwer LibreTranslate
│   ├── search.py        # wyszukiwanie w segmentach wielu plików
│   └── textutil.py      # znaczniki, ogonki, spacje na brzegach
└── ui/                  # interfejs PyQt6
    ├── main_window.py   editor_tab.py   tm_tab.py
    ├── glossary_tab.py  search_tab.py   qa_tab.py
    ├── settings_tab.py  theme.py        workers.py   # wątki robocze
    ├── search_window.py # 🔍 osobne okno wyszukiwania (jak w OmegaT)
    ├── ai_panel.py      # 🤖 zakładka AI: dziennik pracy i polecenie
    ├── quicktrans.py    # ⚡ popup z wieloma silnikami MT
    ├── tmx_editor.py    # 📝 edytor pamięci TM / plików TMX
    └── dialogs/project_dialogs.py
```

Warstwa `core/` nie zależy od Qt — można jej używać w skryptach bez GUI.

```

Warstwa `core/` nie zależy od Qt — można jej używać w skryptach bez GUI.
