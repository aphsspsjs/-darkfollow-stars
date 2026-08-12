import os
import json
import sqlite3
import requests
from decimal import Decimal
from flask import Flask, request

# =========================================================
# إعدادات
# =========================================================

BOT_TOKEN = os.environ["BOT_TOKEN"]
DARKFOLLOW_TOKEN = os.environ["DARKFOLLOW_TOKEN"]

PORT = int(os.environ.get("PORT", "10000"))
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")

# API الخاص بـ DarkFollow / SocPanel
DARKFOLLOW_API = os.environ.get(
    "DARKFOLLOW_API",
    "https://socpanel.com/privateApi/incrementUserBalance"
)

# 100 نجمة = 1 دولار
STARS_PER_DOLLAR = 100

# قاعدة البيانات
DB_FILE = "darkfollow.db"

app = Flask(__name__)

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


# =========================================================
# قاعدة البيانات
# =========================================================

def db():
    connection = sqlite3.connect(DB_FILE)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():

    connection = db()

    connection.execute("""
        CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            charge_id TEXT PRIMARY KEY,
            chat_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            stars INTEGER NOT NULL,
            dollars TEXT NOT NULL,
            status TEXT NOT NULL,
            api_response TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    connection.commit()
    connection.close()


init_db()


# =========================================================
# Telegram API
# =========================================================

def telegram(method, data=None):

    url = f"{TELEGRAM_API}/{method}"

    try:

        response = requests.post(
            url,
            json=data or {},
            timeout=15
        )

        print("Telegram method:", method)
        print("Telegram status:", response.status_code)
        print("Telegram response:", response.text)

        try:
            return response.json()

        except Exception:

            return {
                "ok": False,
                "description": response.text
            }

    except Exception as e:

        print("Telegram ERROR:", repr(e))

        return {
            "ok": False,
            "description": str(e)
        }


# =========================================================
# إرسال رسالة
# =========================================================

def send_message(chat_id, text, reply_markup=None):

    data = {
        "chat_id": chat_id,
        "text": text
    }

    if reply_markup:
        data["reply_markup"] = reply_markup

    return telegram(
        "sendMessage",
        data
    )


# =========================================================
# حفظ حساب DarkFollow
# =========================================================

def save_user(chat_id, username):

    connection = db()

    connection.execute("""
        INSERT INTO users (
            chat_id,
            username
        )
        VALUES (?, ?)

        ON CONFLICT(chat_id)
        DO UPDATE SET
            username = excluded.username,
            updated_at = CURRENT_TIMESTAMP
    """, (
        chat_id,
        username
    ))

    connection.commit()
    connection.close()


def get_user(chat_id):

    connection = db()

    row = connection.execute("""
        SELECT username
        FROM users
        WHERE chat_id = ?
    """, (
        chat_id,
    )).fetchone()

    connection.close()

    if row:
        return row["username"]

    return None


# =========================================================
# تنظيف اسم المستخدم
# =========================================================

def clean_username(username):

    username = str(username or "")
    username = username.strip()
    username = username.lstrip("@")

    return username


# =========================================================
# التحقق من اسم المستخدم
# =========================================================

def valid_username(username):

    username = clean_username(username)

    if not username:
        return False

    if len(username) > 100:
        return False

    for char in username:

        if not (
            char.isalnum()
            or char == "_"
            or char == "."
            or char == "-"
        ):
            return False

    return True


# =========================================================
# إضافة الرصيد إلى DarkFollow
# =========================================================

def add_balance(username, dollars):

    username = clean_username(username)

    # نحافظ على الكسور إذا كانت موجودة
    amount = Decimal(str(dollars))

    params = {
        "loginString": username,
        "amount": str(amount),
        "token": DARKFOLLOW_TOKEN
    }

    print()
    print("========================================")
    print("DARKFOLLOW BALANCE REQUEST")
    print("loginString:", username)
    print("amount:", amount)
    print("========================================")

    try:

        response = requests.get(
            DARKFOLLOW_API,
            params=params,
            timeout=20
        )

        print("DarkFollow HTTP:", response.status_code)
        print("DarkFollow RAW:", response.text)

        # نحاول قراءة JSON
        try:

            data = response.json()

        except Exception:

            data = response.text.strip()

        print("DarkFollow PARSED:", data)

        return {
            "http_status": response.status_code,
            "data": data,
            "raw": response.text
        }

    except Exception as e:

        print("DarkFollow ERROR:", repr(e))

        return {
            "http_status": 0,
            "data": None,
            "raw": "",
            "error": str(e)
        }


# =========================================================
# معرفة هل DarkFollow نجح فعلاً
# =========================================================

def darkfollow_success(result):

    if not result:
        return False

    status = result.get("http_status", 0)

    data = result.get("data")

    # HTTP failure
    if status < 200 or status >= 300:
        return False

    # إذا رجع JSON
    if isinstance(data, dict):

        # حالات نجاح شائعة
        if data.get("ok") is True:
            return True

        if data.get("success") is True:
            return True

        if data.get("status") is True:
            return True

        if str(data.get("status", "")).lower() in (
            "success",
            "successful",
            "ok",
            "true",
            "done"
        ):
            return True

        if str(data.get("result", "")).lower() in (
            "success",
            "successful",
            "ok",
            "true",
            "done"
        ):
            return True

        # بعض APIs ترجع error فقط عند الفشل
        if (
            "error" in data
            or "errors" in data
        ):
            return False

        # إذا HTTP 2xx ولم يوجد خطأ صريح
        # نعتبره نجاحاً
        return True

    # إذا رجع نص
    if isinstance(data, str):

        text = data.strip().lower()

        if text in (
            "1",
            "true",
            "ok",
            "success",
            "successful",
            "done"
        ):
            return True

        # نصوص الخطأ
        error_words = [
            "error",
            "invalid",
            "failed",
            "failure",
            "not found",
            "insufficient",
            "wrong"
        ]

        for word in error_words:

            if word in text:
                return False

        # HTTP 2xx بدون رسالة خطأ
        return True

    return False


# =========================================================
# حفظ الدفع
# =========================================================

def payment_exists(charge_id):

    connection = db()

    row = connection.execute("""
        SELECT status
        FROM payments
        WHERE charge_id = ?
    """, (
        charge_id,
    )).fetchone()

    connection.close()

    return row


def save_payment(
    charge_id,
    chat_id,
    username,
    stars,
    dollars,
    status,
    api_response
):

    connection = db()

    connection.execute("""
        INSERT OR REPLACE INTO payments (
            charge_id,
            chat_id,
            username,
            stars,
            dollars,
            status,
            api_response
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        charge_id,
        chat_id,
        username,
        stars,
        str(dollars),
        status,
        json.dumps(
            api_response,
            ensure_ascii=False,
            default=str
        )
    ))

    connection.commit()
    connection.close()


# =========================================================
# باقات الشحن
# =========================================================

def packages(chat_id):

    keyboard = {
        "inline_keyboard": [

            [
                {
                    "text": "⭐ 100 = $1",
                    "callback_data": "stars:100"
                }
            ],

            [
                {
                    "text": "⭐ 500 = $5",
                    "callback_data": "stars:500"
                }
            ],

            [
                {
                    "text": "⭐ 1000 = $10",
                    "callback_data": "stars:1000"
                }
            ],

            [
                {
                    "text": "⭐ 5000 = $50",
                    "callback_data": "stars:5000"
                }
            ]

        ]
    }

    send_message(
        chat_id,
        "⭐ اختر مبلغ الشحن:",
        keyboard
    )


# =========================================================
# إنشاء فاتورة Telegram Stars
# =========================================================

def send_invoice(chat_id, username, stars):

    username = clean_username(username)

    # مهم:
    # payload صغير وواضح
    payload = json.dumps(
        {
            "username": username,
            "stars": int(stars)
        },
        ensure_ascii=False,
        separators=(",", ":")
    )

    result = telegram(
        "sendInvoice",
        {
            "chat_id": chat_id,

            "title": "شحن رصيد DarkFollow",

            "description":
                f"إضافة {stars} ⭐ إلى رصيد DarkFollow",

            "payload": payload,

            # Telegram Stars
            "currency": "XTR",

            "prices": [
                {
                    "label": f"{stars} Telegram Stars",
                    "amount": int(stars)
                }
            ]
        }
    )

    return result


# =========================================================
# الصفحة الرئيسية
# =========================================================

@app.route("/", methods=["GET"])
def home():

    return "DarkFollow Stars Bot is running!"


# =========================================================
# Health Check
# =========================================================

@app.route("/health", methods=["GET"])
def health():

    return {
        "status": "ok"
    }


# =========================================================
# Webhook
# =========================================================

@app.route("/webhook", methods=["POST"])
def webhook():

    update = request.get_json(
        silent=True
    ) or {}

    print()
    print("========================================")
    print("TELEGRAM UPDATE")
    print(
        json.dumps(
            update,
            ensure_ascii=False,
            indent=2
        )
    )
    print("========================================")

    # =====================================================
    # PRE CHECKOUT
    # =====================================================

    pre = update.get(
        "pre_checkout_query"
    )

    if pre:

        query_id = pre.get("id")

        payload = pre.get(
            "invoice_payload",
            ""
        )

        currency = pre.get(
            "currency"
        )

        total_amount = int(
            pre.get(
                "total_amount",
                0
            )
        )

        print("PRE CHECKOUT")
        print("currency:", currency)
        print("amount:", total_amount)
        print("payload:", payload)

        # لازم يكون XTR
        if currency != "XTR":

            telegram(
                "answerPreCheckoutQuery",
                {
                    "pre_checkout_query_id":
                        query_id,

                    "ok": False,

                    "error_message":
                        "عملة الدفع غير صحيحة."
                }
            )

            return "OK"

        # لازم يكون payload صحيح
        try:

            invoice_data = json.loads(
                payload
            )

            username = clean_username(
                invoice_data["username"]
            )

            expected_stars = int(
                invoice_data["stars"]
            )

            if (
                not username
                or expected_stars <= 0
                or expected_stars != total_amount
            ):

                raise ValueError(
                    "Invalid invoice"
                )

        except Exception as e:

            print(
                "PreCheckout payload error:",
                repr(e)
            )

            telegram(
                "answerPreCheckoutQuery",
                {
                    "pre_checkout_query_id":
                        query_id,

                    "ok": False,

                    "error_message":
                        "بيانات الفاتورة غير صحيحة."
                }
            )

            return "OK"

        # موافقة الدفع
        telegram(
            "answerPreCheckoutQuery",
            {
                "pre_checkout_query_id":
                    query_id,

                "ok": True
            }
        )

        return "OK"

    # =====================================================
    # MESSAGE
    # =====================================================

    message = update.get(
        "message"
    )

    if message:

        chat = message.get(
            "chat",
            {}
        )

        chat_id = chat.get(
            "id"
        )

        text = message.get(
            "text",
            ""
        ).strip()

        # =================================================
        # SUCCESSFUL PAYMENT
        # =================================================

        successful_payment = message.get(
            "successful_payment"
        )

        if successful_payment:

            print()
            print("***************************************")
            print("SUCCESSFUL PAYMENT RECEIVED")
            print("***************************************")

            stars = int(
                successful_payment.get(
                    "total_amount",
                    0
                )
            )

            payload = successful_payment.get(
                "invoice_payload",
                ""
            )

            charge_id = successful_payment.get(
                "telegram_payment_charge_id",
                ""
            )

            currency = successful_payment.get(
                "currency",
                ""
            )

            print("Stars:", stars)
            print("Currency:", currency)
            print("Charge ID:", charge_id)
            print("Payload:", payload)

            # التأكد من العملة
            if currency != "XTR":

                send_message(
                    chat_id,
                    "❌ خطأ: عملة الدفع غير صحيحة."
                )

                return "OK"

            # =================================================
            # منع تكرار العملية
            # =================================================

            old_payment = payment_exists(
                charge_id
            )

            if old_payment:

                print(
                    "Payment already exists:",
                    charge_id
                )

                # إذا سبق نجاحه لا نضيف مرة ثانية
                if old_payment["status"] == "SUCCESS":
                    return "OK"

            # =================================================
            # قراءة Payload
            # =================================================

            try:

                data = json.loads(
                    payload
                )

                username = clean_username(
                    data["username"]
                )

                expected_stars = int(
                    data["stars"]
                )

            except Exception as e:

                print(
                    "PAYLOAD ERROR:",
                    repr(e)
                )

                save_payment(
                    charge_id,
                    chat_id,
                    "",
                    stars,
                    Decimal("0"),
                    "PAYLOAD_ERROR",
                    {
                        "payload": payload,
                        "error": str(e)
                    }
                )

                send_message(
                    chat_id,
                    "❌ تعذر قراءة بيانات عملية الدفع.\n\n"
                    f"رقم العملية:\n{charge_id}"
                )

                return "OK"

            # =================================================
            # التأكد أن مبلغ الدفع مطابق للفاتورة
            # =================================================

            if stars != expected_stars:

                save_payment(
                    charge_id,
                    chat_id,
                    username,
                    stars,
                    Decimal("0"),
                    "AMOUNT_MISMATCH",
                    {
                        "expected": expected_stars,
                        "received": stars
                    }
                )

                send_message(
                    chat_id,
                    "❌ مبلغ الدفع لا يطابق الفاتورة.\n\n"
                    f"رقم العملية:\n{charge_id}"
                )

                return "OK"

            # =================================================
            # حساب الدولار
            # =================================================

            dollars = (
                Decimal(stars)
                / Decimal(STARS_PER_DOLLAR)
            )

            print(
                "Username:",
                username
            )

            print(
                "Stars:",
                stars
            )

            print(
                "Dollars:",
                dollars
            )

            # =================================================
            # إضافة الرصيد
            # =================================================

            result = add_balance(
                username,
                dollars
            )

            print(
                "DarkFollow result:",
                result
            )

            # =================================================
            # نجاح الشحن
            # =================================================

            if darkfollow_success(result):

                save_payment(
                    charge_id,
                    chat_id,
                    username,
                    stars,
                    dollars,
                    "SUCCESS",
                    result
                )

                send_message(
                    chat_id,

                    "✅ تم الشحن بنجاح!\n\n"

                    f"👤 الحساب:\n"
                    f"@{username}\n\n"

                    f"⭐ النجوم:\n"
                    f"{stars}\n\n"

                    f"💵 المضاف إلى DarkFollow:\n"
                    f"${dollars:.2f}\n\n"

                    "تمت إضافة الرصيد إلى الحساب تلقائياً."
                )

                print(
                    "SUCCESS: Balance added."
                )

            # =================================================
            # فشل إضافة الرصيد
            # =================================================

            else:

                save_payment(
                    charge_id,
                    chat_id,
                    username,
                    stars,
                    dollars,
                    "PAID_BUT_NOT_CREDITED",
                    result
                )

                send_message(
                    chat_id,

                    "⚠️ تم استلام الدفع بنجاح، "
                    "لكن تعذر إضافة الرصيد تلقائياً.\n\n"

                    f"👤 الحساب: @{username}\n"

                    f"⭐ النجوم: {stars}\n"

                    f"💵 المبلغ: ${dollars:.2f}\n\n"

                    f"🧾 رقم العملية:\n"
                    f"{charge_id}\n\n"

                    "لا تدفع مرة ثانية. "
                    "تم حفظ العملية."
                )

                print(
                    "WARNING: Payment received "
                    "but DarkFollow credit failed."
                )

            return "OK"

        # =================================================
        # START
        # =================================================

        if text == "/start":

            send_message(
                chat_id,

                "👋 أهلاً بك في بوت شحن DarkFollow\n\n"

                "أرسل اسم مستخدم حسابك في DarkFollow.\n\n"

                "مثال:\n"
                "AbuNasser\n\n"

                "أو:\n"
                "@AbuNasser"
            )

            return "OK"

        # =================================================
        # تغيير الحساب
        # =================================================

        if text in (
            "/account",
            "حسابي",
            "تغيير الحساب"
        ):

            send_message(
                chat_id,

                "👤 أرسل اسم مستخدم حساب DarkFollow الجديد.\n\n"
                "مثال:\n"
                "AbuNasser"
            )

            return "OK"

        # =================================================
        # إذا أرسل username
        # =================================================

        if text:

            username = clean_username(
                text
            )

            if valid_username(username):

                save_user(
                    chat_id,
                    username
                )

                send_message(
                    chat_id,

                    "✅ تم حفظ الحساب:\n\n"

                    f"👤 @{username}\n\n"

                    "اختر مبلغ الشحن:"
                )

                packages(
                    chat_id
                )

                return "OK"

            send_message(
                chat_id,

                "❌ اسم المستخدم غير صحيح.\n\n"

                "أرسل اسم المستخدم فقط.\n"

                "مثال:\n"
                "AbuNasser"
            )

            return "OK"

    # =====================================================
    # CALLBACK QUERY
    # =====================================================

    callback = update.get(
        "callback_query"
    )

    if callback:

        query_id = callback.get(
            "id"
        )

        chat_id = callback.get(
            "message",
            {}
        ).get(
            "chat",
            {}
        ).get(
            "id"
        )

        data = callback.get(
            "data",
            ""
        )

        telegram(
            "answerCallbackQuery",
            {
                "callback_query_id":
                    query_id
            }
        )

        # لازم تكون باقة Stars
        if not data.startswith(
            "stars:"
        ):

            return "OK"

        try:

            stars = int(
                data.split(
                    ":",
                    1
                )[1]
            )

        except Exception:

            return "OK"

        # السماح للباقات المحددة فقط
        allowed_packages = {
            100,
            500,
            1000,
            5000
        }

        if stars not in allowed_packages:

            send_message(
                chat_id,
                "❌ باقة غير صالحة."
            )

            return "OK"

        username = get_user(
            chat_id
        )

        if not username:

            send_message(
                chat_id,

                "❌ لم يتم تحديد حساب DarkFollow.\n\n"
                "أرسل /start"
            )

            return "OK"

        print(
            "Creating invoice:",
            chat_id,
            username,
            stars
        )

        result = send_invoice(
            chat_id,
            username,
            stars
        )

        # إذا فشل إنشاء الفاتورة
        if not result.get("ok"):

            print(
                "INVOICE ERROR:",
                result
            )

            send_message(
                chat_id,

                "❌ تعذر إنشاء فاتورة الدفع.\n\n"
                "حاول مرة أخرى."
            )

        return "OK"

    return "OK"


# =========================================================
# إعداد Webhook
# =========================================================

def set_webhook():

    if not RENDER_URL:

        print(
            "WARNING: RENDER_EXTERNAL_URL "
            "غير موجود."
        )

        return

    webhook_url = (
        f"{RENDER_URL}/webhook"
    )

    print(
        "Setting Telegram webhook:",
        webhook_url
    )

    result = telegram(
        "setWebhook",
        {
            "url": webhook_url,

            # نستقبل فقط الأشياء التي نحتاجها
            "allowed_updates": [
                "message",
                "callback_query",
                "pre_checkout_query"
            ]
        }
    )

    print(
        "Webhook result:",
        result
    )


# =========================================================
# تشغيل
# =========================================================

if __name__ == "__main__":

    set_webhook()

    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False
    )
