#!/usr/bin/env python3
"""Personal Shopper -- gentageligt stress-/haengnings-diagnostik-script.

BAGGRUND: "Personal Shopper" haengte uforklarligt mindst to gange (se
BACKLOG.md/README.md for den fulde historik):
  1. En 8+ timers haengning natten mellem 2026-07-09/10 -- en DIREKTE
     `python3 monitor.py`-koersel (dengang SEKVENTIEL kildeudfoersel, FOER
     ThreadPoolExecutor-parallelliseringen i monitor.py blev bygget) stoppede
     med at logge midt i Reshoppers detalje-opslags-fase. Ingen exception,
     ingen videre aktivitet i 8+ timer.
  2. En kortere (~10-40 min.) stilstand 2026-07-10 under en test af den NYE
     parallelle kildeudfoersel -- men denne har en alternativ, mere
     sandsynlig forklaring (en agents forgrunds-Bash-kald afbrudt af en
     session-interaktion), IKKE noedvendigvis en kodefejl.

Alle netvaerkskald i sources/*.py og turso_io.py har allerede EKSPLICITTE
timeouts (page.goto(timeout=...), requests.get/post(timeout=...),
urlopen(timeout=...)) -- ingen ubegraensede loops/retries fundet ved manuel
gennemgang. De to konkrete mistanker der IKKE var undersoegt dybere var (a)
Playwrights browser.close()/context.close() uden timeout-parameter, og (b)
ressourcekontention naar Reshopper+DBA koerer med hver sin Chromium-browser
SAMTIDIGT (ny risiko, fandtes ikke ved den oprindelige 8-timers-haengning).
Dette script forsoeger at REPRODUCERE en haengning under kontrollerede,
gentagne forhold, med detaljeret PR.-KALD (ikke kun pr.-kilde) tidsstemplet
logging, saa en eventuel fremtidig gentagelse kan lokaliseres PRAECIST.

Uanset om en haengning reproduceres her eller ej: hang_guard.py's
install_hard_watchdog() (nu forankret i monitor.py's main()) er den
generelle garanti mod at en FREMTIDIG variant af "stille haenger i timevis"
nogensinde kan ske igen, upaavirket af denne test-koerslens resultat.

Kør: python3 test_hang_diagnostics.py [--iterations N] [--skip-parallel] [--sources reshopper,dba,sellpy,vinted]

Bruger EN LILLE, KUNSTIG oenskeseddel (de to officielle valideringsposter fra
personal-shopper-brief.md/data/wishlist.local.yaml: Birkholm leggings str.
104, Zara bukser str. 104) -- IKKE den rigtige Turso-oenskeseddel, og skriver
ALDRIG til seen.db/Sheets/Turso (kalder kildernes fetch()/fetch_details()
direkte, uden om monitor.run_source()'s DB-upsert-logik).
"""
import argparse
import concurrent.futures
import datetime
import functools
import json
import logging
import logging.handlers
import statistics
import sys
import threading
import time

import hang_guard
import matching
import monitor

logger = logging.getLogger("personal_shopper.hang_diagnostics")

# UAFHAENGIG haard watchdog for HELE testscriptet -- adskilt fra monitor.py's
# produktions-watchdog (separat kald til samme hang_guard-hjaelper, egen
# timer-instans, egen -- meget rummeligere -- frist). Garanterer at SELVE
# testen heller ikke kan haenge i det uendelige, uanset hvad der maatte gaa
# galt i instrumenteringen nedenfor eller i kildernes egne kald.
TEST_HARD_TIMEOUT_S = 55 * 60  # 55 min. loft for HELE testscriptet

# De to officielle valideringsposter (se data/wishlist.local.yaml) -- holder
# testen hurtig (kun 2 soegetermer pr. kilde pr. iteration) og reproducerbar.
TEST_WISHLIST = [
    {"type": "leggings", "maerke": "Birkholm", "stoerrelse": "104", "maks_pris": 150, "stand": ""},
    {"type": "bukser", "maerke": "Zara", "stoerrelse": "104", "maks_pris": 150, "stand": ""},
]

ALL_SOURCES = ["reshopper", "dba", "sellpy", "vinted"]
PARALLEL_SOURCES = ["reshopper", "dba"]  # samme par som faktisk koerer parallelt i monitor.py

# ── Kald-niveau instrumentering ──────────────────────────────────────────
# Monkey-patcher Playwrights Page.goto/Browser.close/BrowserContext.close SAA
# LAENGE testscriptet koerer, saa vi faar tidsstemplet foer/efter-logging for
# HVERT ENKELT Playwright-kald (ikke kun pr.-kilde-niveau, som monitor.log
# allerede giver via sources/reshopper.py+dba.py's egen logging). Dette er
# strengt additiv instrumentering -- selve kaldets adfaerd/returvaerdi er
# 100% uaendret, vi lytter blot foer/efter.
_call_records: list[dict] = []
_call_records_lock = threading.Lock()


def _record_call(kind: str, label: str, start_wall: str, duration_s: float, ok: bool) -> None:
    with _call_records_lock:
        _call_records.append({
            "kind": kind, "label": label, "start_wall": start_wall,
            "duration_s": duration_s, "ok": ok,
        })


def _instrument_method(cls, method_name: str, kind: str):
    """Wrapper der logger 'KALD-START'/'KALD-SLUT' med tidsstempel + varighed
    omkring ETHVERT kald til cls.method_name (fx Page.goto, Browser.close).
    Returnerer den oprindelige, uwrappede metode saa den kan genskabes bagefter
    (_restore_method) -- vigtigt hvis dette script nogensinde koeres flere
    gange i samme proces (fx fra en test-runner)."""
    original = getattr(cls, method_name)

    @functools.wraps(original)
    def wrapper(self, *args, **kwargs):
        label = args[0] if args else (kwargs.get("url") or kwargs.get("reason") or "")
        label = str(label)[:150]
        start_monotonic = time.monotonic()
        start_wall = datetime.datetime.now().isoformat(timespec="milliseconds")
        logger.info("KALD-START [%s] %s @ %s", kind, label, start_wall)
        ok = True
        try:
            return original(self, *args, **kwargs)
        except Exception:
            ok = False
            raise
        finally:
            duration = time.monotonic() - start_monotonic
            logger.info("KALD-SLUT  [%s] %s -- %.2fs (ok=%s)", kind, label, duration, ok)
            _record_call(kind, label, start_wall, duration, ok)

    setattr(cls, method_name, wrapper)
    return original


def _install_instrumentation() -> dict:
    """Installerer instrumenteringen paa Playwrights Page/Browser/
    BrowserContext-klasser. Import sker HER (ikke paa modul-niveau) saa
    scriptet stadig kan koeres selvom playwright skulle mangle (fx til kun at
    teste Sellpy/Vinted-HTTP-kilderne)."""
    from playwright.sync_api import Browser, BrowserContext, Page
    originals = {
        (Page, "goto"): _instrument_method(Page, "goto", "page.goto"),
        (Browser, "close"): _instrument_method(Browser, "close", "browser.close"),
        (BrowserContext, "close"): _instrument_method(BrowserContext, "close", "context.close"),
    }
    return originals


def _restore_instrumentation(originals: dict) -> None:
    for (cls, method_name), original in originals.items():
        setattr(cls, method_name, original)


# ── Selve test-iterationen ───────────────────────────────────────────────

def run_source_once(name: str, module, config: dict, wishlist: list[dict], iteration: int, mode_label: str) -> dict:
    """Kalder module.fetch() + module.fetch_details() ÉN gang for kilden
    `name` -- samme to-fase-kontrakt og samme precheck()-foerfiltrering som
    monitor.py's run_source(), men UDEN nogen DB/Sheets/Turso-skrivning
    (kaldes direkte, dry_run=True). Fanger ALLE exceptions (logger dem, men
    lader testen fortsaette til naeste iteration/kilde uanset resultat --
    formaalet er at faa saa mange datapunkter som muligt, ikke at stoppe ved
    foerste fejl)."""
    t0 = time.monotonic()
    logger.info("=== [%s] %s#%d -- START ===", mode_label, name, iteration)
    result = {
        "source": name, "mode": mode_label, "iteration": iteration,
        "ok": True, "error": None,
        "fetch_s": None, "fetch_details_s": None,
        "n_raw": 0, "n_candidates": 0, "n_detail_urls": 0, "n_details_ok": 0,
    }
    try:
        search_config = dict(config)
        search_config["search_terms"] = monitor.build_search_terms(wishlist)

        t_fetch0 = time.monotonic()
        raw_listings = module.fetch(search_config, dry_run=True)
        result["fetch_s"] = time.monotonic() - t_fetch0
        result["n_raw"] = len(raw_listings)
        logger.info("[%s] %s#%d: fetch() faerdig paa %.2fs (%d raa annonce(r))",
                    mode_label, name, iteration, result["fetch_s"], result["n_raw"])

        candidate_urls = []
        seen_urls = set()
        by_url = {}
        for listing in raw_listings:
            by_url[listing["url"]] = listing
            if listing["url"] in seen_urls:
                continue
            if any(matching.precheck(wl_item, listing) for wl_item in wishlist):
                candidate_urls.append(listing["url"])
                seen_urls.add(listing["url"])
        result["n_candidates"] = len(candidate_urls)

        already_complete = {u for u in candidate_urls if "seller_name" in by_url[u]}
        new_detail_urls = [u for u in candidate_urls if u not in already_complete]
        result["n_detail_urls"] = len(new_detail_urls)

        t_det0 = time.monotonic()
        details = module.fetch_details(new_detail_urls, search_config, dry_run=True) if new_detail_urls else {}
        result["fetch_details_s"] = time.monotonic() - t_det0
        result["n_details_ok"] = len(details)
        logger.info(
            "[%s] %s#%d: fetch_details() faerdig paa %.2fs (%d/%d kandidat(er) fik detaljer)",
            mode_label, name, iteration, result["fetch_details_s"], result["n_details_ok"], result["n_detail_urls"],
        )
    except Exception as e:
        result["ok"] = False
        result["error"] = repr(e)
        logger.exception("[%s] %s#%d: EXCEPTION under test-iteration", mode_label, name, iteration)
    finally:
        result["total_s"] = time.monotonic() - t0
        logger.info("=== [%s] %s#%d -- SLUT (%.2fs total) ===", mode_label, name, iteration, result["total_s"])
    return result


def run_sequential(config: dict, wishlist: list[dict], iterations: int, sources: list[str]) -> list[dict]:
    """(a) Hver kilde ALENE, sekventielt -- reproducerer forholdene FOER
    parallelliseringen (den oprindelige 8-timers-haengning skete under netop
    denne kadence)."""
    results = []
    for name in sources:
        module = monitor.SOURCE_MODULES[name]
        for i in range(1, iterations + 1):
            results.append(run_source_once(name, module, config, wishlist, i, "sekventiel"))
    return results


def run_parallel(config: dict, wishlist: list[dict], iterations: int) -> list[dict]:
    """(b) Reshopper+DBA koert SAMTIDIGT via samme ThreadPoolExecutor-moenster
    som monitor.py's main() reelt bruger nu -- tester om parallel koersel
    selv trigger noget (ressourcekontention, race conditions i Playwright)."""
    results = []
    for i in range(1, iterations + 1):
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(PARALLEL_SOURCES)) as executor:
            futures = {
                executor.submit(run_source_once, name, monitor.SOURCE_MODULES[name], config, wishlist, i, "parallel"): name
                for name in PARALLEL_SOURCES
            }
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())
    return results


# ── Rapportering ──────────────────────────────────────────────────────────

def _fmt_stats(values: list[float]) -> str:
    if not values:
        return "ingen data"
    return f"n={len(values)} gennemsnit={statistics.mean(values):.2f}s min={min(values):.2f}s max={max(values):.2f}s"


def print_report(results: list[dict]) -> None:
    logger.info("############################################################")
    logger.info("# STRESS-TEST RAPPORT")
    logger.info("############################################################")

    by_group: dict[tuple, list[dict]] = {}
    for r in results:
        key = (r["mode"], r["source"])
        by_group.setdefault(key, []).append(r)

    for (mode, source), rows in sorted(by_group.items()):
        fetch_times = [r["fetch_s"] for r in rows if r["fetch_s"] is not None]
        detail_times = [r["fetch_details_s"] for r in rows if r["fetch_details_s"] is not None]
        total_times = [r["total_s"] for r in rows if r.get("total_s") is not None]
        n_failed = sum(1 for r in rows if not r["ok"])
        logger.info("--- %s / %s (%d iteration(er), %d fejlede) ---", mode, source, len(rows), n_failed)
        logger.info("    fetch():         %s", _fmt_stats(fetch_times))
        logger.info("    fetch_details(): %s", _fmt_stats(detail_times))
        logger.info("    total pr. iter.: %s", _fmt_stats(total_times))
        for r in rows:
            if not r["ok"]:
                logger.info("    FEJL: iteration %d -- %s", r["iteration"], r["error"])

    logger.info("------------------------------------------------------------")
    logger.info("Kald-niveau instrumentering (page.goto / browser.close / context.close):")
    by_kind: dict[str, list[dict]] = {}
    for c in _call_records:
        by_kind.setdefault(c["kind"], []).append(c)
    for kind, calls in sorted(by_kind.items()):
        durations = [c["duration_s"] for c in calls]
        n_failed = sum(1 for c in calls if not c["ok"])
        logger.info("    %s: %s (%d fejlede)", kind, _fmt_stats(durations), n_failed)
        slow = sorted(calls, key=lambda c: c["duration_s"], reverse=True)[:3]
        for c in slow:
            logger.info("        langsomste: %.2fs -- %s @ %s", c["duration_s"], c["label"], c["start_wall"])

    all_total = [r["total_s"] for r in results if r.get("total_s") is not None]
    logger.info("------------------------------------------------------------")
    logger.info("SAMLET: %d iteration(er) i alt, %d fejlede, samlet testtid-sum %.1f min.",
                len(results), sum(1 for r in results if not r["ok"]), sum(all_total) / 60.0 if all_total else 0.0)
    logger.info("############################################################")


def setup_logging(log_path: str) -> None:
    # VIGTIGT: `logger` ("personal_shopper.hang_diagnostics") er et BARN af
    # "personal_shopper" (samme roddel som sources/reshopper.py+dba.py+
    # sellpy.py+vinted.py's loggere) og propagerer derfor som udgangspunkt
    # OP til forældreloggeren. Handlers tilfoejes derfor UDELUKKENDE paa
    # "personal_shopper"-roden -- ellers ville hang_diagnostics' egne linjer
    # (men ikke kildernes) blive logget TO GANGE (én gang via egne handlers,
    # én gang via propagation op til roden, som ogsaa fik handlers).
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)
    file_handler = logging.handlers.RotatingFileHandler(log_path, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(fmt)

    root_source_logger = logging.getLogger("personal_shopper")
    root_source_logger.setLevel(logging.INFO)
    root_source_logger.addHandler(stream)
    root_source_logger.addHandler(file_handler)


def main() -> int:
    parser = argparse.ArgumentParser(description="Personal Shopper -- stress-/haengnings-diagnostik")
    parser.add_argument("--iterations", type=int, default=5, help="Antal gentagelser pr. kilde/moenster (default 5)")
    parser.add_argument("--skip-parallel", action="store_true", help="Spring den parallelle Reshopper+DBA-test over")
    parser.add_argument("--sources", default=",".join(ALL_SOURCES), help="Kommasepareret liste af kilder til den SEKVENTIELLE test")
    parser.add_argument("--log-path", default="test_hang_diagnostics.log")
    args = parser.parse_args()

    setup_logging(args.log_path)
    logger.info("Stress-diagnostik starter -- iterations=%d, skip_parallel=%s, sources=%s",
                args.iterations, args.skip_parallel, args.sources)

    # UAFHAENGIG watchdog for HELE dette testscript -- se modulets docstring.
    test_watchdog = hang_guard.install_hard_watchdog(TEST_HARD_TIMEOUT_S, logger)
    logger.info("Test-watchdog: haard graense sat til %.0f min. for HELE testkoerslen", TEST_HARD_TIMEOUT_S / 60.0)

    config = monitor.load_config()
    sources = [s.strip() for s in args.sources.split(",") if s.strip()]

    originals = None
    try:
        originals = _install_instrumentation()
    except Exception:
        logger.warning("Kunne ikke installere Playwright-kald-instrumentering (playwright evt. ikke installeret) "
                        "-- fortsaetter uden pr.-kald-tidsstempling, kun pr.-kilde-niveau logges", exc_info=True)

    all_results: list[dict] = []
    try:
        logger.info(">>> DEL 1/2: SEKVENTIEL test (hver kilde alene, én ad gangen) <<<")
        all_results.extend(run_sequential(config, TEST_WISHLIST, args.iterations, sources))

        if not args.skip_parallel:
            logger.info(">>> DEL 2/2: PARALLEL test (Reshopper+DBA samtidig, ThreadPoolExecutor) <<<")
            all_results.extend(run_parallel(config, TEST_WISHLIST, args.iterations))
        else:
            logger.info(">>> DEL 2/2: sprunget over (--skip-parallel) <<<")
    finally:
        if originals is not None:
            _restore_instrumentation(originals)
        test_watchdog.cancel()

    print_report(all_results)

    any_failed = any(not r["ok"] for r in all_results)
    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
