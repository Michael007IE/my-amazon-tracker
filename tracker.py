import html
import os
import re
import sys
import time
import requests
from amazoncaptcha import AmazonCaptcha
from playwright.sync_api import sync_playwright

# ==========================================
# CONFIGURATION & SECRETS
# ==========================================
PRODUCT_URL = (
    "https://www.amazon.ie/TP-Link-Deco-X50-5G-AX3000Mbps-Ultra-Fast/dp/B0BZWMLS6P/"
)
TARGET_PRICE = 280.00

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send_telegram_message(html_message: str):
    """Base helper to send HTML-formatted Telegram messages."""
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

    res = requests.post(api_url, json=payload, timeout=10)
    if res.status_code == 200:
        print("[+] Telegram notification sent successfully!")
    else:
        print(f"[!] Failed to send Telegram message: {res.text}")


def send_price_alert(current_price: float):
    """Sends notification when target price threshold is reached."""
    message = (
        f"🚨 <b>Amazon Price Drop Alert!</b>\n\n"
        f"<b>Product:</b> TP-Link Deco X50-5G\n"
        f"<b>New Price:</b> <b>€{current_price:.2f}</b> (Target: &lt; €{TARGET_PRICE:.2f})\n\n"
        f'<a href="{PRODUCT_URL}">View on Amazon</a>'
    )
    send_telegram_message(message)


def send_failure_alert(reason: str):
    """Sends notification when scraper is unable to read the price."""
    safe_reason = html.escape(reason)
    message = (
        f"⚠️ <b>Amazon Tracker Warning</b>\n\n"
        f"Failed to retrieve the current price for <b>TP-Link Deco X50-5G</b>.\n\n"
        f"<b>Reason:</b> <code>{safe_reason}</code>\n\n"
        f'<a href="{PRODUCT_URL}">Check listing manually</a>'
    )
    send_telegram_message(message)


def handle_amazon_captcha(page) -> tuple[bool, str]:
    """Detects and solves Amazon CAPTCHA challenge."""
    try:
        is_captcha = (
            "validateCaptcha" in page.url
            or page.locator("form[action*='validateCaptcha']").is_visible(timeout=2000)
            or page.locator("#captchacharacters").is_visible(timeout=2000)
        )
    except Exception:
        is_captcha = False

    if not is_captcha:
        return True, ""

    print("[*] Amazon CAPTCHA detected. Attempting automated solve...")
    try:
        captcha_img = page.locator(
            "form[action*='validateCaptcha'] img, img[src*='captcha'], div.a-row img"
        ).first
        captcha_img.wait_for(state="visible", timeout=5000)
        img_url = captcha_img.get_attribute("src")

        if not img_url:
            return False, "CAPTCHA image element was found, but src URL was empty."

        captcha = AmazonCaptcha.fromlink(img_url)
        solution = captcha.solve()
        print(f"[*] Solved CAPTCHA text: {solution}")

        page.fill("#captchacharacters", solution, timeout=5000)
        page.click("button[type='submit']", timeout=5000)
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        page.wait_for_timeout(2000)

        if "validateCaptcha" in page.url or page.locator("#captchacharacters").is_visible(timeout=2000):
            return False, "Amazon rejected the CAPTCHA solution or issued a secondary challenge."

        print("[+] CAPTCHA successfully bypassed!")
        return True, ""
    except Exception as e:
        return False, f"CAPTCHA error: {str(e)}"


def extract_price_from_page(page) -> float | None:
    """Extracts price using primary and secondary price selectors."""
    price_element = page.locator(".a-price .a-offscreen").first
    if price_element.is_visible(timeout=5000):
        raw_text = price_element.inner_text()
    else:
        whole = page.locator(".a-price-whole").first
        fraction = page.locator(".a-price-fraction").first

        if whole.is_visible(timeout=3000):
            whole_text = whole.inner_text().strip()
            fraction_text = (
                fraction.inner_text().strip()
                if fraction.is_visible(timeout=1000)
                else "00"
            )
            raw_text = f"{whole_text}.{fraction_text}"
        else:
            return None

    cleaned = re.sub(r"[^\d.,]", "", raw_text).replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def get_current_price(url: str, max_retries: int = 3) -> tuple[float | None, str]:
    """Scrapes price with retries, returning (price, failure_reason)."""
    last_reason = "Unknown error occurred."

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-IE",
            timezone_id="Europe/Dublin",
        )

        page = context.new_page()
        page.add_init_script("delete Object.getPrototypeOf(navigator).webdriver")

        for attempt in range(1, max_retries + 1):
            try:
                print(f"[*] [Attempt {attempt}/{max_retries}] Navigating to: {url}")
                page.goto(url, wait_until="domcontentloaded", timeout=60000)

                # Check and solve CAPTCHA
                captcha_ok, captcha_err = handle_amazon_captcha(page)
                if not captcha_ok:
                    last_reason = captcha_err
                    print(f"[-] Attempt {attempt} failed: {captcha_err}")
                    time.sleep(3)
                    continue

                # Dismiss cookie consent modal if present
                cookie_btn = page.locator("#sp-cc-accept")
                if cookie_btn.is_visible(timeout=3000):
                    cookie_btn.click()

                page.wait_for_timeout(1000)
                price = extract_price_from_page(page)

                if price is not None:
                    context.close()
                    browser.close()
                    return price, ""

                last_reason = "Price element not found (listing might be out of stock, unavailable, or format changed)."
                print(f"[-] Attempt {attempt} failed: {last_reason}")

            except Exception as e:
                last_reason = f"Network or page navigation error: {str(e)}"
                print(f"[!] Scrape error on attempt {attempt}: {last_reason}")

            time.sleep(3)

        context.close()
        browser.close()
        return None, last_reason


if __name__ == "__main__":
    price, error_reason = get_current_price(PRODUCT_URL)

    if price is None:
        print(f"[-] Failed to fetch price: {error_reason}")
        print("[*] Dispatching Telegram failure alert...")
        send_failure_alert(error_reason)
        sys.exit(0)

    print(f"[*] Current Price: €{price:.2f}")

    if price < TARGET_PRICE:
        print("[+] Target met! Sending Telegram notification...")
        send_price_alert(price)
    else:
        print(f"[-] Price €{price:.2f} is still above target (€{TARGET_PRICE:.2f}).")