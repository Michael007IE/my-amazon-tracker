import os
import re
import sys
import requests
from amazoncaptcha import AmazonCaptcha
from playwright.sync_api import sync_playwright

# ==========================================
# CONFIGURATION & SECRETS
# ==========================================
PRODUCT_URL = (
    "https://www.amazon.ie/TP-Link-Deco-X50-5G-AX3000Mbps-Ultra-Fast/dp/B0BZWMLS6P/"
)
TARGET_PRICE = 500.00

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def handle_amazon_captcha(page) -> bool:
    """Detects and solves Amazon's visual CAPTCHA challenge."""
    is_captcha = "validateCaptcha" in page.url or page.locator("form[action*='validateCaptcha']").is_visible(timeout=2000)
    if not is_captcha:
        return True

    print("[*] Amazon CAPTCHA detected. Attempting automated solve...")
    try:
        captcha_img = page.locator("div.a-row img, div.a-box-inner img").first
        img_url = captcha_img.get_attribute("src")
        
        if not img_url:
            print("[!] Could not locate CAPTCHA image URL.")
            return False

        captcha = AmazonCaptcha.fromlink(img_url)
        solution = captcha.solve()
        print(f"[*] Solved CAPTCHA text: {solution}")

        page.fill("#captchacharacters", solution)
        page.click("button[type='submit']")
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        page.wait_for_timeout(2000)

        # Check if CAPTCHA was cleared
        if "validateCaptcha" in page.url or page.locator("#captchacharacters").is_visible(timeout=1000):
            print("[!] CAPTCHA solve rejected or new challenge issued.")
            return False

        print("[+] CAPTCHA successfully bypassed!")
        return True
    except Exception as e:
        print(f"[!] Error solving CAPTCHA: {e}")
        return False


def extract_price_from_page(page) -> float | None:
    """Extracts price using primary and fallback price selectors."""
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


def get_current_price(url: str) -> float | None:
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

        try:
            print(f"[*] Navigating to: {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=60000)

            # Solve CAPTCHA if presented
            if not handle_amazon_captcha(page):
                return None

            # Handle cookie consent banner if present
            cookie_btn = page.locator("#sp-cc-accept")
            if cookie_btn.is_visible(timeout=3000):
                cookie_btn.click()

            page.wait_for_timeout(1000)
            return extract_price_from_page(page)

        except Exception as e:
            print(f"[!] Scrape error: {e}")
            return None
        finally:
            context.close()
            browser.close()


def send_telegram_alert(current_price: float):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[!] Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID secrets.")
        sys.exit(1)

    message = (
        f"🚨 *Amazon Price Drop Alert\\!*\n\n"
        f"*Product:* TP\\-Link Deco X50\\-5G\n"
        f"*New Price:* *€{current_price:.2f}* \\(Target: < €{TARGET_PRICE:.2f}\\)\n\n"
        f"[View on Amazon]({PRODUCT_URL})"
    )

    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "MarkdownV2",
    }

    res = requests.post(api_url, json=payload, timeout=10)
    if res.status_code == 200:
        print("[+] Telegram alert sent successfully!")
    else:
        print(f"[!] Failed to send Telegram message: {res.text}")


if __name__ == "__main__":
    price = get_current_price(PRODUCT_URL)

    if price is None:
        print("[-] Could not retrieve price.")
        sys.exit(1)

    print(f"[*] Current Price: €{price:.2f}")

    if price < TARGET_PRICE:
        print("[+] Target met! Sending Telegram notification...")
        send_telegram_alert(price)
    else:
        print(f"[-] Price €{price:.2f} is still above target (€{TARGET_PRICE:.2f}).")