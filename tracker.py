import html
import os
import re
import sys
import requests
from bs4 import BeautifulSoup

# ==========================================
# CONFIGURATION & SECRETS
# ==========================================
PRODUCT_URL = "https://www.amazon.ie/TP-Link-Deco-X50-5G-AX3000Mbps-Ultra-Fast/dp/B0BZWMLS6P/"
TARGET_PRICE = 280.00

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY")


def send_telegram_message(html_message: str):
    """Sends HTML formatted message to Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[!] Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID secrets.")
        sys.exit(1)

    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": html_message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }

    res = requests.post(api_url, json=payload, timeout=15)
    if res.status_code == 200:
        print("[+] Telegram message sent successfully!")
    else:
        print(f"[!] Failed to send Telegram message: {res.text}")


def send_price_alert(current_price: float):
    message = (
        f"🚨 <b>Amazon Price Drop Alert!</b>\n\n"
        f"<b>Product:</b> TP-Link Deco X50-5G\n"
        f"<b>New Price:</b> <b>€{current_price:.2f}</b> (Target: &lt; €{TARGET_PRICE:.2f})\n\n"
        f'<a href="{PRODUCT_URL}">View on Amazon</a>'
    )
    send_telegram_message(message)


def send_failure_alert(reason: str):
    safe_reason = html.escape(reason)
    message = (
        f"⚠️ <b>Amazon Tracker Warning</b>\n\n"
        f"Failed to retrieve the current price for <b>TP-Link Deco X50-5G</b>.\n\n"
        f"<b>Reason:</b> <code>{safe_reason}</code>\n\n"
        f'<a href="{PRODUCT_URL}">Check listing manually</a>'
    )
    send_telegram_message(message)


def get_current_price() -> tuple[float | None, str]:
    if not SCRAPER_API_KEY:
        return None, "SCRAPER_API_KEY secret is not set."

    # ScraperAPI endpoint with render_js to ensure dynamic pricing loads
    payload = {
        "api_key": SCRAPER_API_KEY,
        "url": PRODUCT_URL,
        "country_code": "eu",
    }

    print("[*] Fetching product page via residential proxy...")
    try:
        response = requests.get("https://api.scraperapi.com/", params=payload, timeout=60)
        
        if response.status_code != 200:
            return None, f"ScraperAPI returned status code {response.status_code}: {response.text[:100]}"

        soup = BeautifulSoup(response.text, "html.parser")

        # Check common Amazon price elements
        price_elem = (
            soup.select_one(".a-price .a-offscreen")
            or soup.select_one("#priceblock_ourprice")
            or soup.select_one("#priceblock_dealprice")
            or soup.select_one(".priceToPay")
        )

        raw_text = ""
        if price_elem:
            raw_text = price_elem.get_text().strip()
        else:
            # Fallback to whole + fraction selectors
            whole = soup.select_one(".a-price-whole")
            fraction = soup.select_one(".a-price-fraction")
            if whole:
                raw_text = whole.get_text().strip()
                if fraction:
                    raw_text = f"{raw_text}.{fraction.get_text().strip()}"

        if not raw_text:
            return None, "Could not find price selectors in the rendered page."

        cleaned = re.sub(r"[^\d.,]", "", raw_text).replace(",", ".")
        return float(cleaned), ""

    except Exception as e:
        return None, f"Scraper error: {str(e)}"


if __name__ == "__main__":
    price, error_reason = get_current_price()

    if price is None:
        print(f"[-] Failed to fetch price: {error_reason}")
        send_failure_alert(error_reason)
        sys.exit(0)

    print(f"[*] Current Price: €{price:.2f}")

    if price < TARGET_PRICE:
        print("[+] Price target met! Sending Telegram notification...")
        send_price_alert(price)
    else:
        print(f"[-] Price €{price:.2f} is still above target (€{TARGET_PRICE:.2f}).")