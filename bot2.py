import time
import threading
import requests
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

CHECK_INTERVAL = 60

PRODUCTS = {
    "Moto G96 5G": "https://www.motorola.in/smartphones-moto-g-96-5g/p?skuId=544",
    "Phone 2": "https://www.motorola.in/smartphones-motorola-razr-fold/p?skuId=650"
}

tracked_phone = "Moto G96 5G"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/137.0.0.0 Safari/537.36"
    )
}


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def send_telegram(message):
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": message
            },
            timeout=20
        )
    except Exception as e:
        print("Telegram Error:", e)


def get_current_phone():
    return tracked_phone, PRODUCTS[tracked_phone]


def get_status_text(status):
    if status is None:
        return "UNKNOWN ⚠️"
    return "IN STOCK ✅" if status else "OUT OF STOCK ❌"


def check_stock(url):
    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=30
        )

        html = response.text

        instock_count = html.count("schema.org/InStock")
        outofstock_count = html.count("schema.org/OutOfStock")

        log(
            f"InStock tags={instock_count} "
            f"OutOfStock tags={outofstock_count}"
        )

        if instock_count > 0:
            return True

        if outofstock_count > 0:
            return False

        return None

    except Exception as e:
        log(f"Error: {e}")
        return None


def telegram_command_listener():
    global tracked_phone

    offset = 0

    while True:
        try:
            response = requests.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                params={
                    "offset": offset,
                    "timeout": 10
                },
                timeout=15
            )

            updates = response.json().get("result", [])

            for update in updates:
                offset = update["update_id"] + 1

                message = update.get("message")

                if not message:
                    continue

                text = message.get("text", "").strip().lower()

                if text == "/phones":
                    send_telegram(
                        "📱 Available Phones\n\n"
                        "1️⃣ Moto G96 5G\n"
                        "2️⃣ Motorola Razr Fold"
                    )

                elif text == "/track1":
                    tracked_phone = "Moto G96 5G"
                    send_telegram(
                        "✅ Now tracking:\nMoto G96 5G"
                    )

                elif text == "/track2":
                    tracked_phone = "Phone 2"
                    send_telegram(
                        "✅ Now tracking:\nMotorola Razr Fold"
                    )

                elif text == "/current":
                    phone_name, _ = get_current_phone()

                    if phone_name == "Phone 2":
                        phone_name = "Motorola Razr Fold"

                    send_telegram(
                        f"📍 Currently Tracking:\n\n{phone_name}"
                    )

                elif text == "/status":
                    phone_name, url = get_current_phone()

                    status = check_stock(url)

                    if phone_name == "Phone 2":
                        phone_name = "Motorola Razr Fold"

                    send_telegram(
                        f"📱 {phone_name}\n\n"
                        f"Status: {get_status_text(status)}"
                    )

        except Exception as e:
            log(f"Command Error: {e}")

        time.sleep(2)


def main():
    send_telegram(
        "📱 Motorola Multi-Stock Tracker Started\n\n"
        "Monitoring both phones simultaneously!\n\n"
        "Commands:\n"
        "/phones\n"
        "/track1\n"
        "/track2\n"
        "/current\n"
        "/status"
    )

    # This thread allows commands to execute seamlessly while the main loop runs
    threading.Thread(
        target=telegram_command_listener,
        daemon=True
    ).start()

    # Track previous status for each phone individually using a dictionary
    previous_statuses = {phone_name: None for phone_name in PRODUCTS.keys()}

    while True:
        # Loop through and check every phone in our product list
        for name, url in PRODUCTS.items():
            display_name = "Motorola Razr Fold" if name == "Phone 2" else name
            log(f"Checking {display_name}")

            current = check_stock(url)

            if current is not None:
                # Send an immediate status message on the very first run for this phone
                if previous_statuses[name] is None:
                    send_telegram(
                        f"Initial Status Check:\n"
                        f"📱 {display_name}\n"
                        f"Status: {get_status_text(current)}\n\n"
                        f"URL: {url}"
                    )
                
                # Send an alert only if transitioning from Out of Stock to In Stock
                elif previous_statuses[name] is False and current is True:
                    send_telegram(
                        f"🚨 MOTOROLA RESTOCK ALERT 🚨\n\n"
                        f"{display_name}\n\n"
                        f"{url}"
                    )

                previous_statuses[name] = current

                log(
                    f"{display_name}: "
                    f"{get_status_text(current)}"
                )

        log(f"Sleeping {CHECK_INTERVAL} seconds until next full check")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()