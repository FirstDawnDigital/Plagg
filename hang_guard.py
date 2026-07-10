"""Personal Shopper -- forsvar-i-dybden mod uforklarlige haengninger.

Baggrund: natten mellem 2026-07-09/10 haengte en direkte `python3 monitor.py`-
koersel i 8+ timer midt i Reshoppers detalje-opslags-fase -- ingen exception,
ingen videre logaktivitet. Alle netvaerkskald i sources/*.py og turso_io.py har
EKSPLICITTE timeouts (page.goto(timeout=...), requests.get/post(timeout=...),
urlopen(timeout=...)), saa den praecise root cause for DEN konkrete haengning
forbliver ubekraeftet (se test_hang_diagnostics.py's stress-test-resultater).
Uanset root cause skal en fremtidig variant af "stille haenger i timevis"
ALDRIG kunne ske igen -- dette modul er det generelle sikkerhedsnet, uafhaengigt
af hvilken specifik operation der maatte haenge.

To lag, men KUN ét af dem endte med at blive brugt paa Playwright-objekter:
  1. install_hard_watchdog() -- en HAARD global graense for HELE processens
     koerselstid (brugt af monitor.py's main() OG af test_hang_diagnostics.py's
     egen, uafhaengige instans). Rammer den, logges en tydelig "WATCHDOG"-
     besked og processen (og enhver Chromium-underproces, se docstring for
     _panic nedenfor) tvinges til at doe. Denne funktion rører ALDRIG noget
     Playwright-objekt direkte -- kun OS-primitiver (threading.Timer,
     os.killpg/os._exit) -- og er derfor sikker at koere fra en anden traad
     end den der ejer en Playwright-session (se punkt 2 nedenfor for hvorfor
     det skel er kritisk).
  2. safe_close() -- en BLOED, lokal graense omkring et closeable-objekts
     close()-kald via en baggrunds-traad + join(timeout). FORSOEGT brugt
     omkring Playwrights browser.close()/context.close() i sources/
     reshopper.py og sources/dba.py (siden Playwrights close()-metoder ikke
     selv understoetter et timeout=-argument, bekraeftet mod installeret
     playwright==1.61.0: kun 'reason'-keyword findes) -- men test
     (test_hang_diagnostics.py, koersel 2026-07-10) afsloerede at dette AKTIVT
     OEDELAEGGER Playwrights sync-API: Playwrights SyncBase._sync() bruger et
     greenlet bundet til det OS-traad der oprindeligt kaldte
     sync_playwright(), og et close()-kald fra en ANDEN traad fejler
     konsekvent med 'greenlet.error: cannot switch to a different thread
     (which happens to have exited)'. Playwrights sync-API er med andre ord
     IKKE traadsikker paa denne maade.

     KONKLUSION: safe_close() bruges IKKE laengere omkring Playwright-
     objekter (sources/reshopper.py og sources/dba.py kalder nu igen
     context.close()/browser.close() direkte, synkront, fra samme traad som
     resten af funktionen). Funktionen er bevaret her som en generel
     hjaelpefunktion for ANDRE, faktisk traadsikre closeable-objekter (fx en
     almindelig socket/fil/DB-forbindelse) -- men BRUG DEN ALDRIG paa et
     Playwright Browser/BrowserContext/Page-objekt. Den reelle beskyttelse
     mod et haengende Playwright-close()-kald er punkt 1 ovenfor (den globale
     proces-watchdog), som IKKE har dette problem netop fordi den aldrig
     roerer selve Playwright-objektet.

Hvorfor traad-baseret og ikke signal.alarm(): signal.alarm() leverer kun til
HOVEDtraaden og passer daarligt til et program der (a) selv bruger traade
(ThreadPoolExecutor i monitor.py) og (b) kalder subprocess.run() med sin egen
timeout andetsteds (trigger_watcher.py) -- to signal-baserede mekanismer i
samme proces kan let forstyrre hinanden. En baggrunds-traad er uafhaengig af
hvilken traad der haenger, saa laenge den haengende operation reelt venter paa
I/O (netvaerk, pipe til en Playwright/Chromium-underproces) -- CPython
frigiver GIL'en under blokerende syscalls, saa watchdog-traaden kan koere og
gribe ind selv mens hovedtraaden sidder fast i netop den slags kald. (Den
eneste situation en traad-baseret watchdog IKKE kan redde os fra er en
hovedtraad fanget i en ren CPU-spin inde i en C-udvidelse der aldrig frigiver
GIL'en -- ikke observeret noget sted i denne kodebase, alle mistaenkte
operationer er I/O-bundne.)
"""
import logging
import os
import signal
import threading

logger = logging.getLogger("personal_shopper.hang_guard")


def install_hard_watchdog(timeout_s: float, target_logger: logging.Logger | None = None) -> threading.Timer:
    """Starter en daemon-traad der TVINGER processen til at doe hvis den ikke
    selv er faerdig (dvs. har kaldt .cancel() paa den returnerede Timer) inden
    `timeout_s` sekunder er gaaet. Kald .cancel() paa returvaerdien saa snart
    det normale arbejde er faerdigt.

    Det er BEVIDST harmloest at glemme at kalde .cancel() ved et helt normalt
    process-exit: traaden er en daemon-traad, saa den forsvinder stiltiende
    naar Python-processen alligevel afsluttes af sig selv -- den fyrer kun hvis
    processen STADIG koerer efter fristen.

    Vaelger `os.killpg` frem for et almindeligt os._exit(1) hvis muligt: en
    haengende Playwright/Chromium-underproces er stadig i live og ville blive
    et forældreloest "zombie"-lignende barn hvis vi kun dræbte selve Python-
    processen (se BACKLOG/undersoegelsen af punkt 3 -- INGEN zombier fundet
    paa maskinen pt., men vi vil ikke SKABE nogen fremover). monitor.py kalder
    os.setsid() tidligt i main() (se der) saa denne proces bliver sin egen
    proces-GRUPPE-leder -- enhver Playwright-driver/Chromium-underproces den
    spawner arver som udgangspunkt samme gruppe, og et SIGKILL til hele
    gruppen (`os.killpg(os.getpgid(0), signal.SIGKILL)`) rydder derfor op
    efter sig selv i stedet for at efterlade orphans. Fejler killpg (fx fordi
    setsid() ikke lykkedes tidligere, eller platformen ikke understoetter det)
    falder vi tilbage til et almindeligt os._exit(1)."""
    log = target_logger or logger

    def _panic() -> None:
        minutes = timeout_s / 60.0
        log.critical(
            "WATCHDOG: monitor.py har koert i over %.0f minutter, afbryder TVUNGET. "
            "Dette er IKKE en almindelig fejl/exception -- det er sikkerhedsnettet "
            "der greb ind fordi processen ikke naaede at faerdiggoere sig selv "
            "indenfor den haarde graense. Undersoeg monitor.log's sidste linjer "
            "FOER denne besked for at se hvor den sad fast.",
            minutes,
        )
        for handler in list(log.handlers) + list(logging.getLogger("personal_shopper").handlers):
            try:
                handler.flush()
            except Exception:
                pass
        try:
            os.killpg(os.getpgid(0), signal.SIGKILL)
        except Exception:
            # os.setsid()/killpg ikke tilgaengeligt eller fejlede -- sidste
            # udvej, dræber i det mindste selve Python-processen.
            os._exit(1)

    timer = threading.Timer(timeout_s, _panic)
    timer.daemon = True
    timer.start()
    return timer


def safe_close(closeable, label: str, timeout_s: float = 15.0, target_logger: logging.Logger | None = None) -> bool:
    """Kalder closeable.close() i en egen daemon-traad og venter op til
    `timeout_s` sekunder paa den.

    ADVARSEL -- BRUG ALDRIG DENNE FUNKTION PAA ET PLAYWRIGHT
    BROWSER/BROWSERCONTEXT/PAGE-OBJEKT: testet og bekraeftet (2026-07-10, se
    modulets docstring) at det oedelaegger Playwrights sync-API, fordi
    SyncBase._sync() bruger et greenlet bundet til det OS-traad der
    oprindeligt aabnede sync_playwright() -- kald fra en ANDEN traad fejler
    med 'greenlet.error: cannot switch to a different thread'.
    sources/reshopper.py og sources/dba.py kalder derfor IGEN
    context.close()/browser.close() direkte og synkront -- denne funktion
    bruges IKKE af dem laengere. Behold kun til rent traadsikre closeable-
    objekter (almindelige sockets/filer/DB-forbindelser).

    Returnerer True hvis close() naaede at faerdiggoere sig selv indenfor
    fristen, False hvis vi gav op og fortsatte alligevel (close-traaden koerer
    videre i baggrunden som en daemon-traad -- den bliver ryddet op naar
    processen til sidst afsluttes, enten normalt eller via
    install_hard_watchdog() ovenfor)."""
    log = target_logger or logger
    done = threading.Event()

    def _run() -> None:
        try:
            closeable.close()
        except Exception:
            log.debug("%s: close() kastede en exception (harmloest, ignoreres)", label, exc_info=True)
        finally:
            done.set()

    t = threading.Thread(target=_run, name=f"safe_close-{label}", daemon=True)
    t.start()
    finished = done.wait(timeout_s)
    if not finished:
        log.warning(
            "%s: close() haenger stadig efter %.0fs -- giver op og fortsaetter uden at vente "
            "yderligere (det haarde watchdog-lag i monitor.py er backstoppet hvis DETTE "
            "ogsaa skulle blokere resten af processen)",
            label, timeout_s,
        )
    return finished
