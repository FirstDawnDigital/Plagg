#!/usr/bin/env python3
"""Personal Shopper -- I1: Trigger-fra-Sheet.

Lader Esbens kone starte en koersel NU direkte fra Google Sheetet (i stedet
for at vente paa naeste 2x-dagligt scheduled task, se README.md) ved at saette
et hak i "Kør nu"-checkboxen i fanen "Kontrolpanel". Denne fil er en LOENGERE-
VARENDE proces der poller den ÉNE checkbox-celle hvert `trigger.poll_interval_s`
sekund (billigt -- ét gspread-kald, IKKE hele Sheetet) og trigger en fuld
`monitor.py`-koersel naar den er sand.

Koeres som en separat, altid-koerende proces ved siden af det eksisterende
2x-dagligt launchd-scheduled-task (se README.md's launchd-eksempel for BEGGE
processer) -- IKKE i stedet for. De to kan koere samtidig uden at kollidere,
fordi hver trigget koersel er en fuldstaendig, selvstaendig `monitor.py`-proces
(samme seen.db/config.yaml), akkurat som en manuel `python monitor.py`-koersel
ville vaere.

Kør: python trigger_watcher.py [--once] [--poll-interval-s N]
"""
import argparse
import datetime
import logging
import logging.handlers
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import monitor
import sheets_output
import turso_io

logger = logging.getLogger("personal_shopper.trigger_watcher")

BASE_DIR = Path(__file__).resolve().parent
MONITOR_SCRIPT = BASE_DIR / "monitor.py"

# Sikkerhedsventil: en trigget koersel maa aldrig kunne haenge i det uendelige
# (fx hvis Reshopper/Playwright fastlaaser sig) og dermed blokere watcheren
# fra nogensinde at nulstille checkboxen/pollede igen.
RUN_TIMEOUT_S = 30 * 60

# Regex mod monitor.py's egen logtekst ("=== Samlet resultat: %d match(es),
# %d saelger-bundle(s) ===") -- bruges KUN til at give et pænt tal i Status-
# cellen, ikke som en kritisk afhaengighed (falder tilbage til en generisk
# "faerdig"-besked hvis logteksten skulle aendre sig).
RESULT_RE = re.compile(r"Samlet resultat:\s*(\d+)\s*match\(es\),\s*(\d+)\s*saelger-bundle\(s\)")

# Kritik-loop 2: ønskeseddel-raekker der springes over (fx tastefejl i Type/
# Størrelse) forsvandt ellers stille -- fanger wishlist.py's advarsel her saa
# Esbens kone kan se det direkte i Status-cellen uden at aabne monitor.log.
SKIP_RE = re.compile(r"SKIPPED_WISHLIST_ROWS=(\d+)")


def setup_logging(log_path: str) -> None:
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(fmt)
    logger.addHandler(stream_handler)
    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)


def _now_str() -> str:
    return datetime.datetime.now().strftime("%d-%m-%Y %H:%M")


def run_monitor_subprocess() -> tuple[bool, str]:
    """Koerer monitor.py som en ADSKILT subprocess -- vurderet mest robust her:
    monitor.py's Playwright-kald koerer sin egen asyncio-event-loop, og
    monitor.main() saetter logging-handlers + laeser sys.argv via argparse.
    Kaldte vi monitor.main() direkte in-process i et loop, ville hver koersel
    tilfoeje endnu et saet loggging-handlers (dublerede logliner) og potentielt
    kollidere med en allerede-koerende event loop i denne proces. Et rent
    subprocess-kald undgaar begge problemer og efterlader watcheren selv helt
    upaavirket uanset hvad der sker inde i monitor.py.

    Returnerer (success, status_besked)."""
    try:
        result = subprocess.run(
            [sys.executable, str(MONITOR_SCRIPT)],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        msg = f"Fejlede: koerslen tog over {RUN_TIMEOUT_S // 60} min. og blev afbrudt"
        logger.error("trigger_watcher: %s", msg)
        return False, msg

    combined_output = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0:
        # Kort besked til Status-cellen -- sidste ikke-tomme linje af stderr
        # (typisk selve exception-beskeden fra en traceback), afkortet.
        tail_lines = [ln.strip() for ln in (result.stderr or "").splitlines() if ln.strip()]
        short_err = tail_lines[-1] if tail_lines else f"exit-kode {result.returncode}"
        msg = f"Fejlede: {short_err[:200]}"
        logger.error("trigger_watcher: monitor.py fejlede (exit %d): %s", result.returncode, short_err)
        return False, msg

    match = RESULT_RE.search(combined_output)
    if match:
        n_matches, n_bundles = match.group(1), match.group(2)
        msg = f"Færdig kl. {datetime.datetime.now().strftime('%H:%M')} ({n_matches} matches, {n_bundles} bundles)"
    else:
        msg = f"Færdig kl. {datetime.datetime.now().strftime('%H:%M')} (se monitor.log for detaljer)"

    skip_match = SKIP_RE.search(combined_output)
    if skip_match and int(skip_match.group(1)) > 0:
        n_skipped = skip_match.group(1)
        msg += f" — OBS: {n_skipped} ønske sprunget over, tjek Ønskeseddel-fanen"

    logger.info("trigger_watcher: monitor.py koerte igennem -- %s", msg)
    return True, msg


class SheetsControlBackend:
    """Tynd adapter der wrapper det EKSISTERENDE Sheets-Kontrolpanel-flow
    (100% uaendret adfaerd, inkl. J3s gul-orange "koersel i gang"-baggrund)
    bag samme read_run_now()/set_status()/finish_run()-kontrakt som
    TursoControlBackend, saa selve poll_once()-loopet nedenfor kan vaere
    backend-agnostisk."""

    def __init__(self, ws):
        self.ws = ws

    def read_run_now(self) -> bool:
        return sheets_output.read_run_now(self.ws)

    def set_status(self, text: str) -> None:
        sheets_output.set_status(self.ws, text)
        sheets_output.lock_control_row(self.ws)  # J3: gul-orange "koersel i gang"-baggrund

    def finish_run(self, status_text: str, last_run_text: str) -> None:
        sheets_output.finish_run(self.ws, status_text, last_run_text)  # nulstiller ogsaa J3-laasen (unlock_control_row)


class TursoControlBackend:
    """Tynd adapter mod turso_io's control-singleton-tabel (G5) -- samme
    kontrakt som SheetsControlBackend. Ingen visuel "laasning" her (J3s
    gul-orange baggrund er en Sheets-specifik detalje), ellers identisk
    read_run_now()/set_status()/finish_run()-adfaerd."""

    def __init__(self, turso_url: str, token: str):
        self.turso_url = turso_url
        self.token = token

    def read_run_now(self) -> bool:
        return turso_io.read_run_now(self.turso_url, self.token)

    def set_status(self, text: str) -> None:
        turso_io.set_status(self.turso_url, self.token, text)

    def finish_run(self, status_text: str, last_run_text: str) -> None:
        turso_io.finish_run(self.turso_url, self.token, status_text, last_run_text)


def poll_once(backend) -> bool:
    """Én runde af poll-loopet: laeser 'Kør nu'-flaget via backend, og hvis
    det er sandt, trigger en fuld koersel og nulstiller kontrolcellerne
    bagefter. `backend` er enten en SheetsControlBackend eller en
    TursoControlBackend (se ovenfor) -- selve loop-logikken herunder
    (timeout, subprocess-kald, regex-parsing af resultat/skip,
    signal-haandtering sker i main()) er UAENDRET fra foer G5, kun
    ws.-kaldene er erstattet af backend.-kald.

    Returnerer True hvis en koersel blev trigget (bruges af --once/tests til
    at bekraefte at flowet rent faktisk udloeste noget)."""
    try:
        run_now = backend.read_run_now()
    except Exception:
        logger.exception("trigger_watcher: kunne ikke laese 'Kør nu'-flaget denne runde, proever igen naeste runde")
        return False

    if not run_now:
        return False

    logger.info("trigger_watcher: 'Kør nu' er sat -- starter koersel")
    try:
        backend.set_status("Kører... (tager typisk 1-3 min.)")
    except Exception:
        logger.exception("trigger_watcher: kunne ikke saette Status='Kører...' (fortsaetter alligevel)")

    # ALT fra selve koerslen fanges her -- watcheren maa ALDRIG crashe/stoppe
    # med at polle, uanset hvad der gaar galt i monitor.py eller i skrivningen
    # af resultatet tilbage til kontrolpanelet.
    try:
        success, status_msg = run_monitor_subprocess()
    except Exception as e:
        logger.exception("trigger_watcher: uventet fejl under koersel-forsoeg")
        success, status_msg = False, f"Fejlede: {str(e)[:200]}"

    try:
        backend.finish_run(status_msg, _now_str())
    except Exception:
        logger.exception(
            "trigger_watcher: koersel afsluttet (success=%s) men kunne ikke opdatere "
            "kontrolpanelet -- 'Kør nu'-flaget staar muligvis stadig sat", success,
        )
    return True


def _install_signal_handlers() -> list:
    """SIGINT (Ctrl+C) og SIGTERM (launchctl stop / kill) skal begge stoppe
    loopet PAENT -- dvs. faerdiggoere en evt. igangvaerende koersel og skrive
    resultatet, ikke bare doe midt i en subprocess. Vi saetter blot et flag;
    _sleep_or_stop() tjekker det mellem hver poll."""
    stop_flags = [False]

    def handler(signum, frame):
        logger.info("trigger_watcher: modtog signal %s -- stopper paent efter denne runde", signum)
        stop_flags[0] = True

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)
    return stop_flags


def _sleep_or_stop(seconds: float, stop_flags: list) -> None:
    """Sover i op til `seconds`, men i smaa bidder saa et Ctrl+C/SIGTERM
    reagerer inden for ~1 sekund i stedet for at skulle vente hele
    poll_interval_s ud."""
    deadline = time.monotonic() + seconds
    while not stop_flags[0] and time.monotonic() < deadline:
        time.sleep(min(1.0, deadline - time.monotonic()))


def main() -> int:
    parser = argparse.ArgumentParser(description="Personal Shopper -- Trigger-fra-Sheet-watcher")
    parser.add_argument("--once", action="store_true", help="Tjek checkbox-cellen ÉN gang og afslut (til test)")
    parser.add_argument("--poll-interval-s", type=float, default=None, help="Override config.yaml's trigger.poll_interval_s (til test)")
    args = parser.parse_args()

    config = monitor.load_config()
    setup_logging(config.get("trigger", {}).get("log_path", "trigger_watcher.log"))

    trigger_cfg = config.get("trigger", {})
    if not trigger_cfg.get("enabled", True):
        logger.info("trigger_watcher: trigger.enabled=false i config.yaml -- stopper med det samme")
        return 0
    poll_interval_s = args.poll_interval_s if args.poll_interval_s is not None else trigger_cfg.get("poll_interval_s", 60)
    # G5: backend vaelges ud fra trigger.source -- default "sheet" hvis
    # noeglen mangler (bagudkompatibilitet med config.yaml-filer skrevet foer
    # G5). Kun "turso" aendrer noget her; "sheet" er 100% samme opsaetning
    # som foer G5.
    trigger_source = trigger_cfg.get("source", "sheet")

    if trigger_source == "turso":
        turso_cfg = config.get("turso", {})
        turso_url, token = turso_io.load_turso_config(turso_cfg.get("secrets_path", "secrets.env"))
        if not turso_url or not token:
            logger.error("trigger_watcher: trigger.source=turso men Turso-credentials mangler i secrets.env -- kan ikke polle. Stopper.")
            return 1
        backend = TursoControlBackend(turso_url, token)
        logger.info("trigger_watcher: poller Turso control-tabellen hvert %ss (Ctrl+C for at stoppe)", poll_interval_s)
    else:
        control_tab_name = trigger_cfg.get("control_tab_name", "Kontrolpanel")
        gs_cfg = config.get("google_sheets", {})
        client = sheets_output.get_sheets_client(gs_cfg["credentials_file"])
        spreadsheet = sheets_output.get_or_create_spreadsheet(client, config, allow_create=False)
        if spreadsheet is None:
            logger.error("trigger_watcher: intet spreadsheet tilgaengeligt (se config.yaml google_sheets.spreadsheet_id) -- kan ikke polle. Stopper.")
            return 1

        ws = sheets_output.ensure_control_tab(spreadsheet, control_tab_name)
        backend = SheetsControlBackend(ws)
        logger.info(
            "trigger_watcher: poller '%s'!%s hvert %ss (Ctrl+C for at stoppe)",
            control_tab_name, sheets_output.CONTROL_CHECKBOX_CELL, poll_interval_s,
        )

    if args.once:
        poll_once(backend)
        return 0

    stop_flags = _install_signal_handlers()
    while not stop_flags[0]:
        poll_once(backend)
        _sleep_or_stop(poll_interval_s, stop_flags)

    logger.info("trigger_watcher: stoppet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
