#!/usr/bin/env python3
"""
Telegram auto-reply bot for HKOTC daily USDT/HKD rates.

Run:
  TELEGRAM_BOT_TOKEN="123456:ABC..." python3 telegram_rate_bot.py

Optional:
  TELEGRAM_ALLOWED_CHAT_ID="123456789" TELEGRAM_BOT_TOKEN="..." python3 telegram_rate_bot.py
"""

from datetime import datetime
from urllib import parse, request
from zoneinfo import ZoneInfo
import json
import os
import time


BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED_CHAT_ID = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "").strip()
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

RATES = {
    "cash": {
        "name": "Cash / 現金交易",
        "buy_rate": 7.8030,
        "sell_rate": 7.7270,
        "spread": "0.80%",
    },
    "transfer": {
        "name": "Bank Transfer / 銀行轉賬",
        "buy_rate": 7.8380,
        "sell_rate": 7.7970,
        "spread": "0.50%",
    },
}

TRIGGERS = (
    "/start",
    "/rate",
    "/today",
    "rate",
    "rates",
    "today",
    "price",
    "quote",
    "匯率",
    "汇率",
    "今日",
    "價格",
    "价格",
    "usdt",
    "hkd",
)


def today_label():
    try:
        now = datetime.now(ZoneInfo("Asia/Hong_Kong"))
    except Exception:
        now = datetime.now()
    return now.strftime("%d %b %Y")


def rate_message():
    cash = RATES["cash"]
    transfer = RATES["transfer"]
    return (
        f"HKOTC USDT/HKD Rate Today ({today_label()})\n\n"
        f"💵 {cash['name']}\n"
        f"Buy USDT: {cash['buy_rate']:.4f} HKD/USDT\n"
        f"Sell USDT: {cash['sell_rate']:.4f} HKD/USDT\n"
        f"Spread: {cash['spread']}\n\n"
        f"🏦 {transfer['name']}\n"
        f"Buy USDT: {transfer['buy_rate']:.4f} HKD/USDT\n"
        f"Sell USDT: {transfer['sell_rate']:.4f} HKD/USDT\n"
        f"Spread: {transfer['spread']}\n\n"
        "Reply with amount and payment method to request an order quote."
    )


def telegram(method, payload=None, timeout=30):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(f"{API_BASE}/{method}", data=data, headers=headers, method="POST")
    with request.urlopen(req, timeout=timeout) as res:
        body = res.read().decode("utf-8")
    result = json.loads(body)
    if not result.get("ok"):
        raise RuntimeError(result)
    return result["result"]


def should_reply(text):
    lower = text.lower().strip()
    return any(trigger in lower for trigger in TRIGGERS)


def send_message(chat_id, text):
    telegram("sendMessage", {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    })


def handle_update(update):
    message = update.get("message") or update.get("edited_message")
    if not message:
        return

    chat = message.get("chat") or {}
    chat_id = str(chat.get("id", ""))
    if ALLOWED_CHAT_ID and chat_id != ALLOWED_CHAT_ID:
        return

    text = message.get("text", "")
    if not text:
        return

    if should_reply(text):
        send_message(chat_id, rate_message())


def main():
    if not BOT_TOKEN:
        raise SystemExit("Missing TELEGRAM_BOT_TOKEN. Example: TELEGRAM_BOT_TOKEN='123:ABC' python3 telegram_rate_bot.py")

    print("HKOTC Telegram rate bot is running. Press Ctrl+C to stop.")
    offset = None
    while True:
        try:
            payload = {"timeout": 25, "allowed_updates": ["message", "edited_message"]}
            if offset is not None:
                payload["offset"] = offset
            updates = telegram("getUpdates", payload, timeout=35)
            for update in updates:
                offset = update["update_id"] + 1
                handle_update(update)
        except KeyboardInterrupt:
            print("\nStopped.")
            break
        except Exception as exc:
            print(f"Bot error: {exc}")
            time.sleep(5)


if __name__ == "__main__":
    main()
