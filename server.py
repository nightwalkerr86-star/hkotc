#!/usr/bin/env python3
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib import request, parse
import json
import os
import ssl

OKX_OTC_TICKER_URL = "https://www.okx.com/v3/c2c/otc-ticker"
OKX_EXCHANGE_RATE_URL = "https://www.okx.com/v3/c2c/tickers/exchangeRate"


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


class Handler(SimpleHTTPRequestHandler):
    def end_json(self, status, payload):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.split("?", 1)[0] == "/api/okx-rate":
            try:
                self.end_json(200, get_okx_rate())
            except Exception as exc:
                self.end_json(502, {"error": "okx_rate_unavailable", "message": str(exc)})
            return
        super().do_GET()


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    server = ThreadingHTTPServer(("127.0.0.1", 8000), Handler)
    print("Serving HKOTC with OKX rate proxy at http://127.0.0.1:8000/")
    server.serve_forever()
