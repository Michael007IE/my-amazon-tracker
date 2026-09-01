import os
import re
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from playwright.sync_api import sync_playwright

# ==========================================
# CONFIGURATION & SECRETS
# ==========================================
PRODUCT_URL = (
    "https://www.amazon.ie/TP-Link-Deco-X50-5G-AX3000Mbps-Ultra-Fast/dp/B0BZWMLS6P/"
)
TARGET_PRICE = 280.00

# Reading from GitHub Secrets
SENDER_EMAIL = os.getenv("MY_EMAIL")
SENDER_APP_PASSWORD = os.getenv("MY_PASSWORD")
RECEIVER_EMAIL = os.getenv("MY_RECIPIENT")

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465


def extract_price_from_page(page) -> float | None:
    """Extracts price using Amazon price selectors."""
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
    """Launches headless Chromium and navigates to the product page."""
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
            print(f"[*] Fetching: {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=60000)

            # Dismiss cookie banner if present
            cookie_accept_button = page.locator("#sp-cc-accept")
            if cookie_accept_button.is_visible(timeout=3000):
                cookie_accept_button.click()

            page.wait_for_timeout(2000)

            # Check if Amazon presented a bot challenge
            if "validateCaptcha" in page.url or page.locator("form[action*='validateCaptcha']").is_visible(timeout=2000):
                print("[!] Blocked by Amazon CAPTCHA on runner.")
                return None

            return extract_price_from_page(page)

        except Exception as e:
            print(f"[!] Error during scrape: {e}")
            return None
        finally:
            context.close()
            browser.close()


def send_price_alert(current_price: float):
    """Sends the alert email via SMTP."""
    if not all([SENDER_EMAIL, SENDER_APP_PASSWORD, RECEIVER_EMAIL]):
        print("[!] Missing email configuration secrets.")
        sys.exit(1)

    subject = f"Price Drop Alert! TP-Link Deco X50-5G is now €{current_price:.2f}"
    body = (
        f"The TP-Link Deco X50-5G price has dropped below €{TARGET_PRICE:.2f}!\n\n"
        f"Current Price: €{current_price:.2f}\n\n"
        f"Buy it here: {PRODUCT_URL}"
    )

    msg = MIMEMultipart()
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECEIVER_EMAIL
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
        server.login(SENDER_EMAIL, SENDER_APP_PASSWORD)
        server.send_message(msg)

    print(f"[+] Alert email sent to {RECEIVER_EMAIL}!")


if __name__ == "__main__":
    price = get_current_price(PRODUCT_URL)

    if price is None:
        print("[-] Could not retrieve price.")
        sys.exit(0)

    print(f"[*] Extracted Price: €{price:.2f}")

    if price < TARGET_PRICE:
        print("[+] Price is below €280.00! Sending notification...")
        send_price_alert(price)
    else:
        print("[-] Price is still above target (€280.00). No email sent.")