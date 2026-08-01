/**
 * openwa/server.js
 * Sidecar leve que o sender.py chama (porta 2900).
 * Faz bridge para o OpenWA REST API (porta 2785).
 *
 * Rotas:
 *   POST /send            { to, text }
 *   POST /send-document   { to, url, filename }
 */

const http = require("http");
const https = require("https");
const url = require("url");

const OPENWA_BASE  = process.env.OPENWA_BASE_URL  || "http://localhost:2785";
const OPENWA_KEY   = process.env.OPENWA_API_KEY   || "";
const SESSION_ID   = process.env.OPENWA_SESSION_ID || "insightzone";
const SECRET       = process.env.INTERNAL_SECRET  || "";
const PORT         = parseInt(process.env.SIDECAR_PORT || "2900", 10);

// ── utilitários ──────────────────────────────────────────────────────────────

function readBody(req) {
  return new Promise((resolve, reject) => {
    let data = "";
    req.on("data", chunk => (data += chunk));
    req.on("end", () => {
      try { resolve(JSON.parse(data || "{}")); }
      catch (e) { reject(e); }
    });
    req.on("error", reject);
  });
}

function openwaRequest(method, path, body) {
  return new Promise((resolve, reject) => {
    const parsed  = new url.URL(OPENWA_BASE + path);
    const isHttps = parsed.protocol === "https:";
    const lib     = isHttps ? https : http;
    const payload = JSON.stringify(body);

    const options = {
      hostname: parsed.hostname,
      port:     parsed.port || (isHttps ? 443 : 80),
      path:     parsed.pathname + parsed.search,
      method,
      headers: {
        "Content-Type":  "application/json",
        "Content-Length": Buffer.byteLength(payload),
        "X-API-Key":     OPENWA_KEY,
      },
    };

    const req = lib.request(options, res => {
      let data = "";
      res.on("data", c => (data += c));
      res.on("end", () => {
        try {
          resolve({ status: res.statusCode, body: JSON.parse(data || "{}") });
        } catch {
          resolve({ status: res.statusCode, body: data });
        }
      });
    });

    req.on("error", reject);
    req.write(payload);
    req.end();
  });
}

// ── formatar número para chatId do WhatsApp ───────────────────────────────────

function toChatId(phone) {
  // Remove tudo excepto dígitos
  const digits = phone.replace(/\D/g, "");
  return `${digits}@c.us`;
}

// ── handlers ─────────────────────────────────────────────────────────────────

async function handleSend(body, res) {
  const { to, text } = body;
  if (!to || !text) {
    res.writeHead(400);
    return res.end(JSON.stringify({ error: "Missing 'to' or 'text'" }));
  }

  const chatId = toChatId(to);
  const result = await openwaRequest(
    "POST",
    `/api/sessions/${SESSION_ID}/messages/send-text`,
    { chatId, text }
  );

  res.writeHead(result.status);
  res.end(JSON.stringify(result.body));
}

async function handleSendDocument(body, res) {
  const { to, url: fileUrl, filename } = body;
  if (!to || !fileUrl) {
    res.writeHead(400);
    return res.end(JSON.stringify({ error: "Missing 'to' or 'url'" }));
  }

  const chatId = toChatId(to);


  const result = await openwaRequest(
    "POST",
    `/api/sessions/${SESSION_ID}/messages/send-file`,
    {
      chatId,
      url:      fileUrl,
      filename: filename || "relatorio.pdf",
      caption:  "",
    }
  );

  res.writeHead(result.status);
  res.end(JSON.stringify(result.body));
}

// ── servidor ─────────────────────────────────────────────────────────────────

const server = http.createServer(async (req, res) => {
  // Validar segredo interno
  const secret = req.headers["x-internal-secret"] || "";
  if (SECRET && secret !== SECRET) {
    res.writeHead(401);
    return res.end(JSON.stringify({ error: "Unauthorized" }));
  }

  res.setHeader("Content-Type", "application/json");

  try {
    const body = await readBody(req);

    if (req.method === "POST" && req.url === "/send") {
      return await handleSend(body, res);
    }

    if (req.method === "POST" && req.url === "/send-document") {
      return await handleSendDocument(body, res);
    }

    if (req.method === "GET" && req.url === "/health") {
      res.writeHead(200);
      return res.end(JSON.stringify({ status: "ok" }));
    }

    res.writeHead(404);
    res.end(JSON.stringify({ error: "Not found" }));

  } catch (err) {
    console.error("Sidecar error:", err);
    res.writeHead(500);
    res.end(JSON.stringify({ error: err.message }));
  }
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`OpenWA sidecar listening on http://127.0.0.1:${PORT}`);
  console.log(`  → Forwarding to OpenWA at ${OPENWA_BASE}`);
  console.log(`  → Session: ${SESSION_ID}`);
});