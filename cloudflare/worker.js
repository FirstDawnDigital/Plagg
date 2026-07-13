/**
 * plagg-api — Cloudflare Worker (Personal Shopper, G5 Fase 2)
 *
 * DEPLOY: cd cloudflare && wrangler deploy
 *
 * Proxyer API-kald fra frontend (docs/index.html) til Turso.
 * Holder TURSO_URL, TURSO_AUTH_TOKEN, PASSWORD_HASH og SESSION_HMAC_SECRET
 * som Cloudflare Secrets, RATE_LIMIT_KV som et bundet KV-namespace.
 *
 * G25 (2026-07-13): erstatter den tidligere delte, raa X-API-Key (synlig i
 * DevTools, ingen session/rate-limiting) med rigtig auth -- PBKDF2-hashet
 * delt husstands-kodeord + HMAC-signerede session-tokens. Mønster og
 * begrundelser porteret DIREKTE fra scraper-boilerplate's worker/src/
 * auth.ts+middleware.ts+rateLimit.ts (framework-uafhaengig kerne, ingen
 * Hono-afhaengighed traekkes ind her) -- se BACKLOG.md's G25 for detaljer.
 *
 * VIGTIGT (porteret laering, IKKE selv genopdaget her): sessionen sendes
 * som "Authorization: Bearer <token>"-HEADER, ALDRIG en cookie. Et tidligere
 * cookie-forsoeg i scraper-boilerplate fejlede reelt i Safari, fordi GitHub
 * Pages (frontend) og denne Worker (API) ligger paa to FORSKELLIGE top-
 * level-domaener -- det goer sessions-cookien third-party fra browserens
 * synspunkt, og Safaris Intelligent Tracking Prevention blokerer ALLE
 * third-party-cookies som standard (uanset SameSite). Login saa ud til at
 * lykkes ét oejeblik og hoppede saa tilbage til login-siden. En Bearer-token
 * gemt i localStorage og sendt som header rammer ikke den begraensning i
 * NOGEN browser. PLAGGs frontend brugte allerede et localStorage-gemt
 * header-moenster (den tidligere X-API-Key) -- kun selve tokenets INDHOLD
 * og VALIDERING aendres, ikke selve transport-moenstret.
 *
 * Skema (se turso_io.py / planen "Turso-skema"): wishlist, matches, bundles,
 * control. matches/bundles filtreres altid på control.current_run_id
 * (generations-swap, se turso_io.py:write_matches_and_bundles).
 *
 * Endpoints:
 *   POST   /api/login          — G25: {password} -> {ok, token}, rate-limited
 *   POST   /api/logout         — G25: symmetri (stateless token, intet at tilbagekalde server-side)
 *   GET    /api/wishlist       — SELECT * FROM wishlist ORDER BY id
 *   POST   /api/wishlist       — validér (kun type påkrævet, G7) + INSERT
 *   DELETE /api/wishlist/:id   — DELETE WHERE id=?
 *   GET    /api/matches        — filtreret på current_run_id
 *   GET    /api/bundles        — samme filter + JSON.parse(items_json)
 *   GET    /api/status         — control-rækken (status/run_now/last_run_at/last_tldr)
 *   POST   /api/trigger        — UPDATE control SET run_now = 1
 *   GET    /api/shipping-estimates  — G30: {land: {avg, count}} pr. kilde
 *   POST   /api/shipping-observation — G30: registrér ét nyt fragt-datapunkt
 */

// G26: CORS laast til en eksplicit allow-liste i stedet for den tidligere
// helt aabne "*". Produktions-domaenet (GitHub Pages) + localhost (enhver
// port) for lokal test -- se BACKLOG.md's G26 for afvejningen. "*" kunne i
// teorien lade en HVILKEN SOM HELST hjemmeside forsoege at kalde API'et fra
// en besoegendes browser; en eksplicit allow-liste stopper det allerede i
// browseren, foer forespoergslen naar Workeren.
const ALLOWED_ORIGINS = [
  "https://firstdawndigital.github.io",
];
// Lokal test (python -m http.server el. lign.) koerer typisk paa
// http://localhost:<port> eller http://127.0.0.1:<port> -- portnummeret
// varierer fra test til test, saa vi matcher praefikset i stedet for at
// vedligeholde en liste af specifikke portnumre.
const ALLOWED_ORIGIN_PREFIXES = ["http://localhost:", "http://127.0.0.1:"];

function isAllowedOrigin(origin) {
  if (!origin) return false;
  if (ALLOWED_ORIGINS.includes(origin)) return true;
  return ALLOWED_ORIGIN_PREFIXES.some((prefix) => origin.startsWith(prefix));
}

function getCorsHeaders(request) {
  const origin = request.headers.get("Origin");
  const headers = {
    "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
    // G25: "Authorization" erstatter "X-API-Key" -- sessionen sendes nu som
    // en Bearer-token-header, ikke en raa delt noegle. INGEN "Access-Control-
    // Allow-Credentials" -- den er kun relevant for cookie-baseret auth
    // (som vi bevidst IKKE bruger, se modulets docstring).
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Vary": "Origin", // svaret afhaenger af Origin-headeren -- maa ikke caches paa tvaers af oprindelser
  };
  // Ekko KUN den specifikke, whitelistede Origin tilbage (aldrig "*").
  if (isAllowedOrigin(origin)) {
    headers["Access-Control-Allow-Origin"] = origin;
  }
  return headers;
}

// ── G25: auth (PBKDF2-hashing + HMAC-signerede sessions) ────────────────────
// Porteret 1:1 fra scraper-boilerplate/worker/src/auth.ts -- ren Web Crypto
// API, INGEN tredjeparts-bibliotek, INGEN Hono-afhaengighed.

// 100_000, IKKE et hoejere "mere sikkert" tal: Cloudflare Workers' AEGTE
// produktions-crypto.subtle haandhaever et HAARDT loft paa 100.000 PBKDF2-
// iterationer ("NotSupportedError: iteration counts above 100000 are not
// supported"). Dette var et REELT fund i scraper-boilerplate (IKKE
// selv genopdaget her): en tidligere 210.000-vaerdi bestod enhver unit-test
// og "wrangler dev" (lokal simulation haandhaever IKKE graensen) -- men
// ETHVERT login fejlede i den AEGTE deployede Worker, fordi verifyPassword()s
// catch-all fangede NotSupportedError og returnerede false, umuligt at
// skelne fra et forkert kodeord. AENDRES ALDRIG uden at genverificere mod en
// RIGTIGT deployet Worker, ikke kun tests/wrangler dev.
const PBKDF2_ITERATIONS = 100_000;
const HASH_BYTE_LENGTH = 32;

function toBase64Url(bytes) {
  const arr = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  let binary = "";
  for (const byte of arr) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function fromBase64Url(value) {
  const padded = value.replace(/-/g, "+").replace(/_/g, "/");
  const pad = (4 - (padded.length % 4)) % 4;
  const binary = atob(padded + "=".repeat(pad));
  const arr = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) arr[i] = binary.charCodeAt(i);
  return arr;
}

async function pbkdf2(password, salt, iterations) {
  const keyMaterial = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveBits"]
  );
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", hash: "SHA-256", salt, iterations }, keyMaterial, HASH_BYTE_LENGTH * 8
  );
  return new Uint8Array(bits);
}

function constantTimeEqual(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}

async function hashPassword(password) {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const derived = await pbkdf2(password, salt, PBKDF2_ITERATIONS);
  return `pbkdf2$${PBKDF2_ITERATIONS}$${toBase64Url(salt)}$${toBase64Url(derived)}`;
}

async function verifyPassword(password, stored) {
  const parts = stored.split("$");
  if (parts.length !== 4 || parts[0] !== "pbkdf2") return false;
  const iterations = Number.parseInt(parts[1], 10);
  if (!Number.isFinite(iterations) || iterations <= 0) return false;
  try {
    const salt = fromBase64Url(parts[2]);
    const expected = fromBase64Url(parts[3]);
    const actual = await pbkdf2(password, salt, iterations);
    return constantTimeEqual(actual, expected);
  } catch {
    return false; // ugyldig base64url i en gemt hash -- kast ALDRIG paa daarligt input
  }
}

async function hmacKey(secret) {
  return crypto.subtle.importKey(
    "raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign", "verify"]
  );
}

async function createSessionToken(payload, secret) {
  const key = await hmacKey(secret);
  const body = toBase64Url(new TextEncoder().encode(JSON.stringify(payload)));
  const signature = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(body));
  return `${body}.${toBase64Url(signature)}`;
}

async function verifySessionToken(token, secret) {
  const [body, signature] = token.split(".");
  if (!body || !signature) return null;
  try {
    const key = await hmacKey(secret);
    const valid = await crypto.subtle.verify("HMAC", key, fromBase64Url(signature), new TextEncoder().encode(body));
    if (!valid) return null;
    const payload = JSON.parse(new TextDecoder().decode(fromBase64Url(body)));
    if (typeof payload.exp !== "number" || payload.exp < Math.floor(Date.now() / 1000)) {
      return null; // udloebet
    }
    return payload;
  } catch {
    return null; // ugyldigt token -- kast ALDRIG, behandl blot som uautentificeret
  }
}

function parseBearerToken(header) {
  if (!header || !header.startsWith("Bearer ")) return null;
  const token = header.slice("Bearer ".length).trim();
  return token || null;
}

// FRAMEWORK-UAFHAENGIG kerne (tager kun raa strenge) -- se modulets docstring.
async function authenticateRequest(authorizationHeader, hmacSecret) {
  const token = parseBearerToken(authorizationHeader);
  if (!token) return null;
  return verifySessionToken(token, hmacSecret);
}

// ── G25: login-rate-limiting (Workers KV) ────────────────────────────────────
// Porteret 1:1 fra scraper-boilerplate/worker/src/rateLimit.ts. Bind et KV-
// namespace som RATE_LIMIT_KV i wrangler.toml (oprettet via
// `wrangler kv namespace create RATE_LIMIT_KV`).
const RATE_LIMIT_WINDOW_SECONDS = 15 * 60;
const RATE_LIMIT_MAX_ATTEMPTS = 5;

async function checkAndIncrementLoginAttempts(kv, ip) {
  const key = `login_attempts:${ip}`;
  const current = Number.parseInt((await kv.get(key)) ?? "0", 10);
  if (current >= RATE_LIMIT_MAX_ATTEMPTS) {
    return { allowed: false };
  }
  await kv.put(key, String(current + 1), { expirationTtl: RATE_LIMIT_WINDOW_SECONDS });
  return { allowed: true };
}

function json(data, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json", ...extraHeaders },
  });
}

// ── Turso HTTP API ────────────────────────────────────────────────────────────
async function tursoExecute(env, sql, args = []) {
  // libsql:// → https://
  const baseUrl = env.TURSO_URL.replace("libsql://", "https://");
  const endpoint = `${baseUrl}/v2/pipeline`;

  const res = await fetch(endpoint, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.TURSO_AUTH_TOKEN}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      requests: [
        { type: "execute", stmt: { sql, args } },
        { type: "close" },
      ],
    }),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Turso HTTP ${res.status}: ${text}`);
  }

  const data = await res.json();
  const result = data.results?.[0];

  if (!result || result.type === "error") {
    throw new Error(`SQL fejl: ${result?.error?.message ?? "ukendt"}`);
  }

  const { cols, rows } = result.response.result;
  const colNames = cols.map((c) => c.name);

  // Turso returnerer værdier som {type, value}-objekter
  return rows.map((row) => {
    const obj = {};
    colNames.forEach((name, i) => {
      const cell = row[i];
      if (cell === null || cell?.type === "null") {
        obj[name] = null;
      } else if (typeof cell === "object" && "value" in cell) {
        // Konverter tal-strenge til tal
        const v = cell.value;
        obj[name] =
          (cell.type === "integer" || cell.type === "float") && v !== null
            ? Number(v)
            : v;
      } else {
        obj[name] = cell;
      }
    });
    return obj;
  });
}

// ── Request handler ───────────────────────────────────────────────────────────
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const corsHeaders = getCorsHeaders(request);

    // CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders });
    }

    const responseHeaders = {
      ...corsHeaders,
      "Content-Type": "application/json",
    };

    const path = url.pathname;

    try {
      // ── POST /api/login — G25, INGEN auth kraevet (det er selve login) ───
      if (path === "/api/login" && request.method === "POST") {
        let body;
        try {
          body = await request.json();
        } catch {
          body = {};
        }
        const password = typeof body.password === "string" ? body.password : "";
        if (!password) {
          return json({ error: "password er påkrævet" }, 400, responseHeaders);
        }

        // Rate-limit FOER selve kodeords-tjekket -- forhindrer et script i
        // at gaette ubegraenset mange gange mod dette endpoint. Nøglet paa
        // IP alene (ikke ogsaa brugernavn, som PLAGG ikke har -- ét delt
        // husstands-kodeord, se BACKLOG.md's G25).
        const ip = request.headers.get("CF-Connecting-IP") || "ukendt";
        const { allowed } = await checkAndIncrementLoginAttempts(env.RATE_LIMIT_KV, ip);
        if (!allowed) {
          return json({ error: "for mange loginforsøg -- prøv igen senere" }, 429, responseHeaders);
        }

        const valid = await verifyPassword(password, env.PASSWORD_HASH);
        if (!valid) {
          return json({ error: "forkert adgangskode" }, 401, responseHeaders);
        }

        const maxAgeDays = Number(env.SESSION_TOKEN_MAX_AGE_DAYS || "30");
        const maxAgeSeconds = maxAgeDays * 24 * 60 * 60;
        const token = await createSessionToken(
          { sub: "husstand", exp: Math.floor(Date.now() / 1000) + maxAgeSeconds },
          env.SESSION_HMAC_SECRET
        );
        // Token i JSON-body, IKKE en cookie -- se modulets docstring om
        // hvorfor (Safari ITP + third-party-cookie-blokering).
        return json({ ok: true, token }, 200, responseHeaders);
      }

      // ── ALLE andre endpoints kraever en gyldig session ────────────────────
      const session = await authenticateRequest(request.headers.get("Authorization"), env.SESSION_HMAC_SECRET);
      if (!session) {
        return json({ error: "Unauthorized" }, 401, responseHeaders);
      }

      // ── POST /api/logout — G25, symmetri ─────────────────────────────────
      // Stateless token (ingen server-side sessions-lager) -- der er intet
      // at tilbagekalde server-side. Selve "log ud" er frontend'en der
      // sletter sit gemte token. Endpointet findes for symmetri/fremtidig
      // brug (fx en denylist) og for at kraeve et gyldigt token foer det
      // bekraefter noget.
      if (path === "/api/logout" && request.method === "POST") {
        return json({ ok: true }, 200, responseHeaders);
      }

      // ── GET /api/wishlist ────────────────────────────────────────────────
      if (path === "/api/wishlist" && request.method === "GET") {
        const rows = await tursoExecute(env, "SELECT * FROM wishlist ORDER BY id");
        return json(rows, 200, responseHeaders);
      }

      // ── POST /api/wishlist ───────────────────────────────────────────────
      if (path === "/api/wishlist" && request.method === "POST") {
        const d = await request.json();

        // G5-FIX (fund #3): server-side validering FOER Turso-kaldet. Uden
        // dette blev fx maks_pris="abc" til NaN -> null i Turso-kaldet, som
        // Turso saa afviste med en raa 400-fejlbesked der blev lækket direkte
        // til klienten (NOT NULL-constraint-fejl fra SQLite, ikke en
        // forstaaelig besked). Negative priser blev tidligere accepteret
        // uden validering.
        // G7: kun TYPE er paakraevet. Stoerrelse er nu valgfri (tom = "stoerrelse
        // er ikke et kriterie", fx legetoej/boeger uden toejstoerrelse).
        const typeStr = typeof d.type === "string" ? d.type.trim() : "";
        const stoerrelseStr = typeof d.stoerrelse === "string" ? d.stoerrelse.trim() : "";
        if (!typeStr) {
          return json({ error: "type er påkrævet" }, 400, responseHeaders);
        }

        const maksPrisNum = Number(d.maks_pris);
        if (d.maks_pris == null || !Number.isFinite(maksPrisNum) || maksPrisNum <= 0) {
          return json({ error: "maks_pris skal være et positivt tal" }, 400, responseHeaders);
        }

        const rows = await tursoExecute(
          env,
          `INSERT INTO wishlist (type, maerke, stoerrelse, maks_pris, stand)
           VALUES (?, ?, ?, ?, ?)
           RETURNING *`,
          [
            { type: "text", value: typeStr },
            { type: "text", value: String(d.maerke || "") },
            { type: "text", value: stoerrelseStr },
            { type: "float", value: maksPrisNum },
            { type: "text", value: String(d.stand || "") },
          ]
        );
        return json(rows[0] ?? { ok: true }, 201, responseHeaders);
      }

      // ── DELETE /api/wishlist/:id ─────────────────────────────────────────
      const wishlistMatch = path.match(/^\/api\/wishlist\/(\d+)$/);
      if (wishlistMatch && request.method === "DELETE") {
        const id = parseInt(wishlistMatch[1], 10);
        const deleted = await tursoExecute(
          env,
          "DELETE FROM wishlist WHERE id = ? RETURNING id",
          [{ type: "integer", value: String(id) }]
        );
        if (deleted.length === 0) {
          return json({ error: `Ønskeseddel-item ${id} ikke fundet` }, 404, responseHeaders);
        }
        return json({ ok: true }, 200, responseHeaders);
      }

      // ── GET /api/matches — filtreret på current_run_id ──────────────────
      if (path === "/api/matches" && request.method === "GET") {
        const rows = await tursoExecute(
          env,
          `SELECT * FROM matches
           WHERE run_id = (SELECT current_run_id FROM control WHERE id = 1)
           ORDER BY updated_at DESC`
        );
        return json(rows, 200, responseHeaders);
      }

      // ── GET /api/bundles — samme filter + JSON.parse(items_json) ────────
      if (path === "/api/bundles" && request.method === "GET") {
        const rows = await tursoExecute(
          env,
          `SELECT * FROM bundles
           WHERE run_id = (SELECT current_run_id FROM control WHERE id = 1)
           ORDER BY updated_at DESC`
        );
        for (const r of rows) {
          try {
            r.items = JSON.parse(r.items_json || "[]");
          } catch {
            r.items = [];
          }
        }
        return json(rows, 200, responseHeaders);
      }

      // ── GET /api/status ──────────────────────────────────────────────────
      if (path === "/api/status" && request.method === "GET") {
        const rows = await tursoExecute(env, "SELECT * FROM control WHERE id = 1");
        return json(rows[0] ?? null, 200, responseHeaders);
      }

      // ── POST /api/trigger ────────────────────────────────────────────────
      if (path === "/api/trigger" && request.method === "POST") {
        await tursoExecute(
          env,
          "UPDATE control SET run_now = 1, updated_at = datetime('now') WHERE id = 1"
        );
        return json({ ok: true }, 200, responseHeaders);
      }

      // ── GET /api/shipping-estimates — G30 ────────────────────────────────
      // {land: {avg, count}} for ALLE lande med mindst ÉN observation for
      // 'source' (default "vinted") -- samme form som turso_io.py's
      // get_shipping_estimates(), saa webappen kan bruge samme struktur.
      // MIN_SHIPPING_OBSERVATIONS-graensen haandhaeves IKKE her (se
      // turso_io.py's docstring) -- klienten tjekker selv 'count'.
      if (path === "/api/shipping-estimates" && request.method === "GET") {
        const source = url.searchParams.get("source") || "vinted";
        const rows = await tursoExecute(
          env,
          `SELECT country, AVG(shipping_price) as avg_price, COUNT(*) as n
           FROM shipping_observations WHERE source = ? GROUP BY country`,
          [{ type: "text", value: source }]
        );
        const estimates = {};
        for (const r of rows) {
          estimates[r.country] = { avg: Math.round(r.avg_price * 100) / 100, count: r.n };
        }
        return json(estimates, 200, responseHeaders);
      }

      // ── POST /api/shipping-observation — G30 ─────────────────────────────
      // Body: {country, shipping_price, source?}. Registrerer ÉT nyt
      // manuelt observeret fragt-datapunkt (fra webappens blyant-dialog,
      // eller et seeding-script) -- overskriver ALDRIG en tidligere
      // observation, se turso_io.py's add_shipping_observation()-docstring.
      if (path === "/api/shipping-observation" && request.method === "POST") {
        const d = await request.json();
        const countryStr = typeof d.country === "string" ? d.country.trim().toUpperCase() : "";
        const sourceStr = typeof d.source === "string" && d.source.trim() ? d.source.trim() : "vinted";
        const priceNum = Number(d.shipping_price);

        // Serverside-validering (samme princip som POST /api/wishlist ovenfor)
        // -- et ISO 3166-1 alpha-2-landekode-format (2 bogstaver), en positiv,
        // realistisk fragtpris (graenser valgt rummeligt, ikke en praecis
        // forretningsregel -- blot for at fange indtastningsfejl som "4500"
        // for "45,00" eller en negativ/nul-vaerdi).
        if (!/^[A-Z]{2}$/.test(countryStr)) {
          return json({ error: "country skal være en 2-bogstavs landekode (fx 'PL')" }, 400, responseHeaders);
        }
        if (!Number.isFinite(priceNum) || priceNum <= 0 || priceNum > 2000) {
          return json({ error: "shipping_price skal være et positivt tal (maks. 2000 kr.)" }, 400, responseHeaders);
        }

        await tursoExecute(
          env,
          "INSERT INTO shipping_observations (source, country, shipping_price) VALUES (?, ?, ?)",
          [
            { type: "text", value: sourceStr },
            { type: "text", value: countryStr },
            { type: "float", value: priceNum },
          ]
        );
        return json({ ok: true }, 201, responseHeaders);
      }

      return json({ error: "Not found" }, 404, responseHeaders);
    } catch (err) {
      return json({ error: err.message }, 500, responseHeaders);
    }
  },
};
