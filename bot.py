import time
import threading
from datetime import datetime
from playwright.sync_api import sync_playwright
import requests

# ─────────────────────────────────────────────
#  CONFIGURATION  — edit only this section
# ─────────────────────────────────────────────
TELEGRAM_TOKEN = "8945976477:AAHIvjWR5cgglrWeddLIZlBvuIvoxNvUI14"
CHAT_ID        = "1205353437"
PINCODE        = "244001"
CHECK_INTERVAL = 300   # seconds between scans (5 min)

PRODUCT_URLS = {
    "White Whey Protein":               "https://shop.amul.com/en/product/amul-whey-protein-32-g-or-pack-of-30-sachets",
    "Chocolate Whey Protein":           "https://shop.amul.com/en/product/amul-chocolate-whey-protein-34-g-or-pack-of-30-sachets",
    "Daily Creamer":                    "https://shop.amul.com/en/product/amul-dairy-creamer-3-g-or-pack-of-120-sachets",
    "Lactose Free Milk":                "https://shop.amul.com/en/product/amul-lactose-free-milk-250-ml-or-pack-of-32",
    "High Protein Rose Lassi":          "https://shop.amul.com/en/product/amul-high-protein-rose-lassi-200-ml-or-pack-of-30",
    "High Protein Blueberry Shake":     "https://shop.amul.com/en/product/amul-high-protein-blueberry-shake-200-ml-or-pack-of-30",
    "High Protein Plain Lassi":         "https://shop.amul.com/en/product/amul-high-protein-plain-lassi-200-ml-or-pack-of-30",
    "High Protein Buttermilk":          "https://shop.amul.com/en/product/amul-high-protein-buttermilk-200-ml-or-pack-of-30",
    "High Protein Wheat Flour":         "https://shop.amul.com/en/product/amul-high-protein-wheat-flour-65-g-or-pack-of-30-sachets",
    "Kool Protein Milkshake Chocolate": "https://shop.amul.com/en/product/amul-kool-protein-milkshake-or-chocolate-180-ml-or-pack-of-8",
}

# ─────────────────────────────────────────────
#  GLOBALS
# ─────────────────────────────────────────────
last_known_status: dict[str, bool] = {}
scan_lock   = threading.Lock()
is_scanning = False


# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────
def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _is_in_stock(html: str) -> bool | None:
    if "schema.org/InStock" in html:
        return True

    if "schema.org/OutOfStock" in html:
        return False

    return None


# ─────────────────────────────────────────────
#  TELEGRAM
# ─────────────────────────────────────────────
def tg_send(text: str):
    url     = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10).raise_for_status()
    except Exception as e:
        print(f"[TG ERROR] {e}")


def tg_get_updates(offset: int) -> list[dict]:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    try:
        r = requests.get(url, params={"offset": offset, "timeout": 10}, timeout=15)
        return r.json().get("result", [])
    except Exception:
        return []


# ─────────────────────────────────────────────
#  STOCK CHECK
# ─────────────────────────────────────────────
def check_all_products() -> dict[str, bool]:
    results = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled"
            ]
        )

        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/148.0.0.0 Safari/537.36"
            ),
            locale="en-IN",
            viewport={"width": 1366, "height": 768}
        )

        context.add_cookies([{
            "name": "location",
            "value": PINCODE,
            "domain": "shop.amul.com",
            "path": "/"
        }])

        for name, url in PRODUCT_URLS.items():

            page = context.new_page()

            try:
                print(f"[{_ts()}] Checking {name}")

                page.goto(
                    url,
                    wait_until="networkidle",
                    timeout=60000
                )

                try:
                    page.fill(
                        'input[placeholder*="PINCODE"]',
                        PINCODE
                    )
                    time.sleep(2)
                    page.keyboard.press("Enter")
                    time.sleep(5)
                except Exception:
                    pass

                page.screenshot(path="debug.png")

                print("CURRENT URL:", page.url)
                print("TITLE:", page.title())

                time.sleep(5)

                html = page.content()

                in_stock = _is_in_stock(html)

                if in_stock is None:
                    print(
                        f"[{_ts()}] ⚠️ Availability tag not found for {name}"
                    )

                    debug_file = (
                        name.replace(" ", "_")
                        .replace("/", "_")
                        + ".html"
                    )

                    with open(
                        debug_file,
                        "w",
                        encoding="utf-8"
                    ) as f:
                        f.write(html)

                    print(
                        f"[{_ts()}] Saved HTML to {debug_file}"
                    )

                    in_stock = last_known_status.get(
                        name,
                        False
                    )

                results[name] = in_stock

                icon = "✅" if in_stock else "❌"

                print(
                    f"[{_ts()}] {icon} {name}: "
                    f"{'IN STOCK' if in_stock else 'OUT OF STOCK'}"
                )

            except Exception as e:

                print(
                    f"[{_ts()}] ❌ Error checking "
                    f"{name}: {e}"
                )

                results[name] = last_known_status.get(
                    name,
                    False
                )

            finally:
                page.close()

            time.sleep(2)

        browser.close()

    return results


# ─────────────────────────────────────────────
#  SCAN + NOTIFY
# ─────────────────────────────────────────────
def run_scan_and_notify(triggered_by_command=False):
    global last_known_status, is_scanning

    with scan_lock:
        is_scanning = True

    try:
        print(f"[{_ts()}] 🔍 Starting scan...")
        current = check_all_products()

        if triggered_by_command:
            lines = ["📦 *Current Stock Status*\n"]
            for name, in_stock in current.items():
                icon = "✅" if in_stock else "❌"
                lines.append(f"{icon} {name}")
            tg_send("\n".join(lines))

        else:
            new_in_stock = [
                name for name, in_stock in current.items()
                if in_stock and not last_known_status.get(name, False)
            ]
            if new_in_stock:
                alert = "🚨 *AMUL RESTOCK ALERT!* 🚨\n\n"
                for name in new_in_stock:
                    alert += f"✅ [{name}]({PRODUCT_URLS[name]})\n"
                alert += "\n🛒 [Browse all protein products](https://shop.amul.com/en/browse/protein)"
                tg_send(alert)
                print(f"[{_ts()}] 🚨 Alert sent for: {new_in_stock}")

        last_known_status.update(current)

    finally:
        with scan_lock:
            is_scanning = False


# ─────────────────────────────────────────────
#  TELEGRAM COMMAND LISTENER
# ─────────────────────────────────────────────
def command_listener():
    offset = 0
    print(f"[{_ts()}] 💬 Command listener ready.")
    while True:
        updates = tg_get_updates(offset)
        for update in updates:
            offset = update["update_id"] + 1
            msg    = update.get("message") or update.get("channel_post")
            if not msg:
                continue
            if str(msg.get("chat", {}).get("id", "")) != CHAT_ID:
                continue
            text = msg.get("text", "").strip().lower()

            if text.startswith("/status"):
                if is_scanning:
                    tg_send("⏳ A scan is already running — give it a moment.")
                else:
                    tg_send("🔍 Checking all products now, give me ~2 minutes...")
                    threading.Thread(
                        target=run_scan_and_notify,
                        kwargs={"triggered_by_command": True},
                        daemon=True
                    ).start()

            elif text.startswith("/help"):
                tg_send(
                    "🤖 *Amul Stock Tracker — Commands*\n\n"
                    "/status — Check all products right now\n"
                    "/help   — Show this message\n\n"
                    f"Scans run automatically every {CHECK_INTERVAL // 60} minutes."
                )
        time.sleep(2)


# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────
def main():
    print("🚀 Amul Restock Tracker starting...")
    tg_send(
        "🤖 *Amul Tracker is Online!*\n\n"
        f"Watching *{len(PRODUCT_URLS)}* products.\n"
        f"Scans every {CHECK_INTERVAL // 60} minutes.\n\n"
        "Send /status for an instant check, /help for commands."
    )

    threading.Thread(target=command_listener, daemon=True).start()
    run_scan_and_notify()

    while True:
        print(f"[{_ts()}] 💤 Next scan in {CHECK_INTERVAL}s...")
        time.sleep(CHECK_INTERVAL)
        run_scan_and_notify()


if __name__ == "__main__":
    main()