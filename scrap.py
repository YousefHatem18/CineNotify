import sys

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib
import re
import json
import os
import time
from datetime import datetime, timedelta


from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# بيانات الفيلم والصفحة
MOVIE_NAME = "Avengers: Doomsday"
MOVIE_SLUG = "avengers-doomsday"

# رابط الصفحة المجمعة للسينمتين
COMBINED_URL = f"https://egy.voxcinemas.com/ar/showtimes?c=city-centre-almaza&c=mall-of-egypt&m={MOVIE_SLUG}"

# قائمة السينمات المراد مراقبتها بالروابط المحددة
CINEMAS = [
    {
        "id": "city-centre-almaza",
        "name": "سيتي سنتر ألماظة",
        "url": "https://egy.voxcinemas.com/ar/showtimes?c=city-centre-almaza&m=avengers-doomsday&d=20261223",
    },
    {
        "id": "mall-of-egypt",
        "name": "مول مصر",
        "url": "https://egy.voxcinemas.com/ar/showtimes?c=mall-of-egypt&m=avengers-doomsday",
    },
]

# ملف حفظ التواريخ المرصودة لكل سينما لتجنب التكرار
KNOWN_DATES_FILE = "known_dates.json"

# إعدادات البريد من متغيرات البيئة
sender_email = os.environ.get("SENDER_EMAIL", "")
app_password = os.environ.get("APP_PASSWORD", "")
receiver_email = os.environ.get("RECEIVER_EMAIL", "")


def sendEmail(new_days_by_cinema: dict[str, list[dict]]):
    """إرسال إيميل موحد يوضح الأيام الجديدة لكل سينما بشكل منظم"""
    if not (sender_email and app_password and receiver_email):
        print("⚠️ لم يتم العثور على بيانات البريد الإلكتروني في متغيرات البيئة.")
        return

    subject = f"🎬 {MOVIE_NAME} - فتحت أيام جديدة للحجز في سينما ڤوكس!"

    body = f"تم فتح أيام جديدة لحجز فيلم {MOVIE_NAME}:\n\n"

    for cinema_name, days in new_days_by_cinema.items():
        body += f"📍 {cinema_name}:\n"
        for day in days:
            body += f"  📅 {day['label']} ({day['date']})\n"
        body += "\n"

    body += f"🔗 رابط مقارنة المواعيد والحجز المباشر:\n{COMBINED_URL}\n"

    msg = MIMEMultipart()
    msg["From"] = sender_email
    msg["To"] = receiver_email
    msg["Subject"] = subject

    msg.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(sender_email, app_password)
        server.send_message(msg)

    print("✅ Email Sent")


def load_known_dates() -> dict[str, set]:
    """يرجّع قاموس فيه مجموعة الأيام المحفوظة لكل سينما"""
    if not os.path.exists(KNOWN_DATES_FILE):
        return {}
    try:
        with open(KNOWN_DATES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return {k: set(v) for k, v in data.items()}
            elif isinstance(data, list):
                return {}
    except Exception as e:
        print(f"⚠️ تعذر قراءة {KNOWN_DATES_FILE}: {e}")
    return {}


def save_known_dates(data_by_cinema: dict[str, set]):
    """يحفظ الأيام الحالية لكل سينما في ملف JSON"""
    serializable = {k: sorted(list(v)) for k, v in data_by_cinema.items()}
    with open(KNOWN_DATES_FILE, "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)


def get_available_dates(url: str, retries: int = 2) -> list[dict] | None:
    """فتح متصفح مخصص واستخراج جميع الأيام من شريط المواعيد لرابط معين مع محاولة إعادة عند الفشل"""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-http2")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
    options.page_load_strategy = "eager"

    for attempt in range(1, retries + 1):
        driver = None
        raw_days = []
        try:
            driver = webdriver.Chrome(options=options)
            driver.set_page_load_timeout(25)

            driver.get(url)
            wait = WebDriverWait(driver, 20)

            all_days = wait.until(
                EC.presence_of_all_elements_located(
                    (By.CSS_SELECTOR, ".viewport ol li")
                )
            )
            print(f"إجمالي عدد الأيام في شريط الصفحة: {len(all_days)}")

            for day_li in all_days:
                # استخدام textContent لقراءة النص حتى لو كان العنصر خارج حدود الشاشة المرئية
                raw_text = day_li.get_attribute("textContent").strip()
                # إزالة المسافات الزائدة والأسطر
                label = " ".join(raw_text.split())

                link = day_li.find_elements(By.TAG_NAME, "a")
                span = day_li.find_elements(By.TAG_NAME, "span")

                date_code = None
                href = None

                if link:
                    href = link[0].get_attribute("href")
                    match = re.search(r"[?&]d=(\d{8})", href or "")
                    if match:
                        date_code = match.group(1)
                elif span:
                    href = driver.current_url

                raw_days.append({
                    "label": label,
                    "date": date_code,
                    "url": href,
                    "is_span": bool(span),
                })

            # حل كود التاريخ لليوم المحدد الحالي (span) بدقة
            for i, item in enumerate(raw_days):
                if not item["date"]:
                    # 1. فحص ما إذا كان الرابط الحالي يحتوي على ?d=YYYYMMDD
                    current_match = re.search(r"[?&]d=(\d{8})", driver.current_url)
                    if current_match:
                        item["date"] = current_match.group(1)
                    else:
                        # 2. حساب التاريخ بالنسبة للأيام المجاورة
                        if i + 1 < len(raw_days) and raw_days[i + 1]["date"]:
                            next_dt = datetime.strptime(raw_days[i + 1]["date"], "%Y%m%d")
                            item["date"] = (next_dt - timedelta(days=1)).strftime("%Y%m%d")
                        elif i > 0 and raw_days[i - 1]["date"]:
                            prev_dt = datetime.strptime(raw_days[i - 1]["date"], "%Y%m%d")
                            item["date"] = (prev_dt + timedelta(days=1)).strftime("%Y%m%d")

            # تنظيف وإرجاع النتائج النهائية
            results = [
                {"label": d["label"], "date": d["date"], "url": d["url"]}
                for d in raw_days if d["label"] and d["date"]
            ]

            if results:
                return results
            else:
                print(f"⚠️ محاولة {attempt}/{retries}: تم تحميل الصفحة ولكن لم يتم استخراج أي مواعيد صالحة.")

        except Exception as e:
            print(f"⚠️ محاولة {attempt}/{retries} فشلت أثناء جلب المواعيد من {url}: {e}")

        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

        if attempt < retries:
            time.sleep(3)

    return None


if __name__ == "__main__":
    known_dates_by_cinema = load_known_dates()
    updated_known_dates = dict(known_dates_by_cinema)
    new_days_by_cinema = {}

    for cinema in CINEMAS:
        c_id = cinema["id"]
        c_name = cinema["name"]
        c_url = cinema["url"]

        print(f"\n==========================================")
        print(f"🔍 فحص سينما: {c_name}")
        print(f"🔗 الرابط: {c_url}")
        print(f"==========================================")

        available = get_available_dates(c_url)
        if not available:
            print(f"⚠️ فشل جلب المواعيد لـ {c_name} (خطأ في التحميل أو الصفحة فارغة). تم تخطي التحديث والاحتفاظ بالتواريخ السابقة.")
            continue

        for d in available:
            print(f" - {d['label']}  ({d['date']})")

        current_codes = {d["date"] for d in available if d["date"]}
        known_codes = known_dates_by_cinema.get(c_id, set())

        new_codes = current_codes - known_codes
        if new_codes:
            new_days = [d for d in available if d["date"] in new_codes]
            new_days_by_cinema[c_name] = new_days
            print(f"✨ أيام جديدة ظهرت في {c_name}: {[d['label'] for d in new_days]}")
        else:
            print(f"✔️ لا توجد أيام جديدة في {c_name}.")

        updated_known_dates[c_id] = current_codes

    if new_days_by_cinema:
        print("\n📬 تم رصد أيام جديدة! جاري إرسال الإشعار البريدي...")
        sendEmail(new_days_by_cinema)
        save_known_dates(updated_known_dates)
    else:
        print("\nمفيش أيام جديدة في أي سينما عن آخر مرة.")
        if updated_known_dates != known_dates_by_cinema:
            save_known_dates(updated_known_dates)
