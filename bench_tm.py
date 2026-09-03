"""Benchmark TM – pomiar wąskich gardeł przed optymalizacją."""
import os, random, string, tempfile, time

from supercat.core.tm import TranslationMemory

WORDS = ["system", "network", "device", "settings", "user", "password", "file", "open",
         "close", "install", "update", "server", "client", "database", "manual", "press",
         "button", "configure", "connection", "software", "hardware", "version", "error"]


def sentence(n=10):
    return " ".join(random.choice(WORDS) for _ in range(n)).capitalize() + "."


def main():
    random.seed(42)
    tmp = tempfile.mkdtemp()
    tm = TranslationMemory()
    tm.init_for_project(tmp)

    for size in (1000, 5000, 20000):
        tm.clear()
        rows = [(sentence(), "PL " + sentence(), "en", "pl") for _ in range(size)]
        t0 = time.perf_counter()
        tm.add_many(rows)
        t_add = time.perf_counter() - t0

        queries = [sentence() for _ in range(20)]
        t0 = time.perf_counter()
        for q in queries:
            tm.find_fuzzy_matches(q, 70, 5)
        t_search = (time.perf_counter() - t0) / len(queries)

        # symulacja "Zastosuj TM do wszystkich" dla 500 segmentów
        segs = [sentence() for _ in range(500)]
        t0 = time.perf_counter()
        for s in segs[:50]:
            tm.find_fuzzy_matches(s, 80, 1)
        t_apply50 = time.perf_counter() - t0

        print(f"TM {size:>6} wpisów | add_many {t_add:6.2f}s | "
              f"1 wyszukanie {t_search*1000:8.1f} ms | "
              f"50 segmentów {t_apply50:6.2f}s | 500 segm. ≈ {t_apply50*10:6.1f}s")

    tm.close()


if __name__ == "__main__":
    main()
