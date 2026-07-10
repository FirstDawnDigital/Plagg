/**
 * plagg-api — Cloudflare Worker (Personal Shopper, G5 Fase 2)
 *
 * DEPLOY: cd cloudflare && wrangler deploy
 *
 * Proxyer API-kald fra frontend (docs/index.html) til Turso.
 * Holder TURSO_URL, TURSO_AUTH_TOKEN og API_KEY som Cloudflare Secrets.
 * Samme mønster som CC ARCHIVE/ejendompython/cloudflare/worker.js
 * (tursoExecute()-hjælper mod /v2/pipeline, X-API-Key-auth, åben CORS).
 *
 * Skema (se turso_io.py / planen "Turso-skema"): wishlist, matches, bundles,
 * control. matches/bundles filtreres altid på control.current_run_id
 * (generations-swap, se turso_io.py:write_matches_and_bundles).
 *
 * Endpoints:
 *   GET    /api/wishlist       — SELECT * FROM wishlist ORDER BY id
 *   POST   /api/wishlist       — validér (kun type påkrævet, G7) + INSERT
 *   DELETE /api/wishlist/:id   — DELETE WHERE id=?
 *   GET    /api/matches        — filtreret på current_run_id
 *   GET    /api/bundles        — samme filter + JSON.parse(items_json)
 *   GET    /api/status         — control-rækken (status/run_now/last_run_at/last_tldr)
 *   POST   /api/trigger        — UPDATE control SET run_now = 1
 */

// CORS — åben for alle origins da API_KEY er den reelle sikkerhedsmekanisme
const CORS_ORIGIN = "*";

function getCorsHeaders() {
  return {
    "Access-Control-Allow-Origin": CORS_ORIGIN,
    "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-API-Key",
  };
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
    const corsHeaders = getCorsHeaders();

    // CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders });
    }

    const responseHeaders = {
      ...corsHeaders,
      "Content-Type": "application/json",
    };

    // Valider API-nøgle — alle endpoints kræver den
    const apiKey = request.headers.get("X-API-Key");
    if (!apiKey || apiKey !== env.API_KEY) {
      return new Response(JSON.stringify({ error: "Unauthorized" }), {
        status: 401,
        headers: responseHeaders,
      });
    }

    try {
      const path = url.pathname;

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

      return json({ error: "Not found" }, 404, responseHeaders);
    } catch (err) {
      return json({ error: err.message }, 500, responseHeaders);
    }
  },
};
