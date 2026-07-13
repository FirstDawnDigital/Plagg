#!/usr/bin/env python3
"""One-off G30 seeding: post manually-collected Vinted shipping observations
to POST /api/shipping-observation. Logs in via POST /api/login (G25 auth)
to get a Bearer session token first -- the endpoint no longer accepts a
bare API key. Password is prompted interactively, never hardcoded/stored.
"""
import getpass
import sys
import time

import requests

WORKER_URL = "https://plagg-api.proqual.workers.dev"

OBSERVATIONS = {
    "PL": [37.51] * 10,
    "SE": [36.04, 36.04, 37.65, 36.04, 37.65, 36.04, 36.04, 36.04, 36.04, 36.04],
    "FI": [62.79] * 10,
}


def login(password: str) -> str:
    res = requests.post(f"{WORKER_URL}/api/login", json={"password": password}, timeout=10)
    if not res.ok:
        sys.exit(f"Login fejlede ({res.status_code}): {res.text}")
    return res.json()["token"]


def post_observation(token: str, country: str, price: float) -> None:
    res = requests.post(
        f"{WORKER_URL}/api/shipping-observation",
        headers={"Authorization": f"Bearer {token}"},
        json={"country": country, "shipping_price": price},
        timeout=10,
    )
    if not res.ok:
        sys.exit(f"Observation fejlede for {country}={price} ({res.status_code}): {res.text}")


def main() -> None:
    password = getpass.getpass("Plagg-adgangskode: ")
    token = login(password)

    total = sum(len(v) for v in OBSERVATIONS.values())
    done = 0
    for country, prices in OBSERVATIONS.items():
        for price in prices:
            post_observation(token, country, price)
            done += 1
            print(f"[{done}/{total}] {country}: {price} kr. registreret")
            time.sleep(0.2)

    res = requests.get(f"{WORKER_URL}/api/shipping-estimates", headers={"Authorization": f"Bearer {token}"}, timeout=10)
    print("\nNuvaerende estimater:", res.json())


if __name__ == "__main__":
    main()
