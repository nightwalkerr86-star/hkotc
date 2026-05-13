#!/usr/bin/env python3
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib import request, parse
import base64
import json
import os
import ssl

OKX_OTC_TICKER_URL = "https://www.okx.com/v3/c2c/otc-ticker"
OKX_EXCHANGE_RATE_URL = "https://www.okx.com/v3/c2c/tickers/exchangeRate"
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
ALLOWED_JSON_FILES = {
    "blog-posts.json": "blog-posts.json",
    "channel-posts.json": "channel-posts.json",
    "otc-web/blog-posts.json": "blog-posts.json",
    "otc-web/channel-posts.json": "channel-posts.json",
}



def fetch_okx_number(url, field):
    query = parse.urlencode({
        "baseCurrency": "USDT",
        "quoteCurrency": "HKD",
    })
    req = request.Request(
        f"{url}?{query}",
        headers={
            "accept": "application/json",
            "user-agent": "HKOTC-local-rate-proxy/1.0",
        },
        method="GET",
    )

    context = ssl._create_unverified_context()
    with request.urlopen(req, timeout=10, context=context) as res:
        body = json.loads(res.read().decode("utf-8"))

    if str(body.get("code")) not in ("0", "None"):
        raise RuntimeError(body.get("error_message") or body.get("msg") or "OKX request failed")

    try:
        return float(body["data"][field])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"No OKX {field} returned") from exc


def get_okx_rate():
    try:
        rate = fetch_okx_number(OKX_OTC_TICKER_URL, "otcTicker")
        source_field = "otcTicker"
    except Exception:
        rate = fetch_okx_number(OKX_EXCHANGE_RATE_URL, "exchangeRate")
        source_field = "exchangeRate"

    return {
        "source": "OKX P2P",
        "asset": "USDT",
        "fiat": "HKD",
        "rate": round(rate, 4),
        "sourceField": source_field,
        "change": 0,
    }


def safe_json_path(raw_path):
    key = (raw_path or "").lstrip("/")
    mapped = ALLOWED_JSON_FILES.get(key)
    if not mapped:
        raise ValueError("File path is not allowed")
    return os.path.join(ROOT_DIR, mapped)


def read_json_file(raw_path):
    file_path = safe_json_path(raw_path)
    if not os.path.exists(file_path):
        return []
    with open(file_path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json_file(raw_path, data):
    file_path = safe_json_path(raw_path)
    tmp_path = f"{file_path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(data if isinstance(data, list) else [], fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp_path, file_path)


def safe_upload_path(raw_path):
    rel = (raw_path or "").lstrip("/")
    if not rel.startswith("uploads/") or ".." in rel.split("/"):
        raise ValueError("Upload path is not allowed")
    full_path = os.path.abspath(os.path.join(ROOT_DIR, rel))
    uploads_root = os.path.abspath(os.path.join(ROOT_DIR, "uploads"))
    if not full_path.startswith(uploads_root + os.sep):
        raise ValueError("Upload path is not allowed")
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    return full_path


class Handler(SimpleHTTPRequestHandler):
    def end_json(self, status, payload):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def read_request_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8") if length else "{}"
        return json.loads(body or "{}")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path, _, query = self.path.partition("?")
        params = parse.parse_qs(query)
        if path == "/api/okx-rate":
            try:
                self.end_json(200, get_okx_rate())
            except Exception as exc:
                self.end_json(502, {"error": "okx_rate_unavailable", "message": str(exc)})
            return
        if path == "/api/content":
            try:
                data = read_json_file(params.get("path", [""])[0])
                self.end_json(200, {"data": data})
            except Exception as exc:
                self.end_json(400, {"error": "read_failed", "message": str(exc)})
            return
        super().do_GET()

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/content":
            try:
                payload = self.read_request_json()
                write_json_file(payload.get("path", ""), payload.get("data", []))
                self.end_json(200, {"ok": True})
            except Exception as exc:
                self.end_json(400, {"error": "write_failed", "message": str(exc)})
            return
        if path == "/api/upload-image":
            try:
                payload = self.read_request_json()
                upload_path = safe_upload_path(payload.get("path", ""))
                content = base64.b64decode(payload.get("content", ""), validate=True)
                with open(upload_path, "wb") as fh:
                    fh.write(content)
                rel = "/" + os.path.relpath(upload_path, ROOT_DIR).replace(os.sep, "/")
                self.end_json(200, {"ok": True, "url": rel})
            except Exception as exc:
                self.end_json(400, {"error": "upload_failed", "message": str(exc)})
            return
        self.send_error(404, "Not found")


if __name__ == "__main__":
    os.chdir(ROOT_DIR)
    server = ThreadingHTTPServer(("127.0.0.1", 8000), Handler)
    print("Serving HKOTC with OKX rate proxy at http://127.0.0.1:8000/")
    server.serve_forever()
