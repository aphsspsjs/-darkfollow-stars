import os
import json
import requests
from flask import Flask, request

# =========================
# إعدادات
# =========================

BOT_TOKEN = os.environ["BOT_TOKEN"]
DARKFOLLOW_TOKEN = os.environ["DARKFOLLOW_TOKEN"]

PORT = int(os.environ.get("PORT", 10000))
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL")

app = Flask(__name__)

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# DarkFollow / SocPanel
DARKFOLLOW_API = "https://socpanel.com/privateApi/incrementUserBalance"

# 100 نجمة = 1 دولار
STARS_PER_DOLLAR = 100

# تخزين المستخدمين مؤقتاً
users = {}

# منع تكرار إضافة نفس عملية الدفع أثناء تشغيل البوت
processed_payments = set()


# =========================
# Telegram API
# =========================

def telegram(method, data=None):

    try:
        r = requests.post(
            f"{TELEGRAM_API}/{method}",
            json=data or {},
            timeout=30
        )

        return r.json()

    except Exception as e:

        print("Telegram Error:", e)

        return {
            "ok": False,
            "error": str(e)
        }


# =========================
# إضافة الرصيد في DarkFollow
# =========================

def add_balance(username, amount):

    # إزالة @ إذا المستخدم كتبها
    username = username.strip().lstrip("@")

    params = {
        "loginString": username,
        "amount": int(amount),
        "token": DARKFOLLOW_TOKEN
    }

    print("DarkFollow Request:", {
        "loginString": username,
        "amount": int(amount)
    })

    try:

        r = requests.get(
            DARKFOLLOW_API,
            params=params,
            timeout=30
        )

        print("DarkFollow Status:", r.status_code)
        print("DarkFollow Response:", r.text)

        try:
            return r.json()

        except Exception:

            return {
                "ok": False,
                "response": r.text
            }

    except Exception as e:

        print("DarkFollow Error:", e)

        return {
            "ok": False,
            "error": str(e)
        }


# =========================
# إرسال فاتورة Stars
# =========================

def send_invoice(chat_id, username, stars):

    username = username.strip().lstrip("@")

    payload = json.dumps({
        "darkfollow_username": username,
        "stars": stars
    })

    return telegram(
        "sendInvoice",
        {
            "chat_id": chat_id,

            "title": "شحن DarkFollow",

            "description":
            f"شحن رصيد DarkFollow بقيمة {stars} ⭐",

            "payload": payload,

            "currency": "XTR",

            "prices": [
                {
                    "label": f"{stars} Telegram Stars",
                    "amount": stars
                }
            ]
        }
    )


# =========================
# باقات الشحن
# =========================

def packages(chat_id):

    keyboard = {
        "inline_keyboard": [

            [
                {
                    "text": "100 ⭐ = $1",
                    "callback_data": "100"
                }
            ],

            [
                {
                    "text": "500 ⭐ = $5",
                    "callback_data": "500"
                }
            ],

            [
                {
                    "text": "1000 ⭐ = $10",
                    "callback_data": "1000"
                }
            ],

            [
                {
                    "text": "5000 ⭐ = $50",
                    "callback_data": "5000"
                }
            ]

        ]
    }

    telegram(
        "sendMessage",
        {
            "chat_id": chat_id,

            "text":
            "⭐ اختر مبلغ الشحن:",

            "reply_markup": keyboard
        }
    )


# =========================
# الصفحة الرئيسية
# =========================

@app.route("/", methods=["GET"])
def home():

    return "DarkFollow Stars Bot is running!"


# =========================
# Webhook
# =========================

@app.route("/webhook", methods=["POST"])
def webhook():

    update = request.get_json(
        silent=True
    ) or {}

    # ==================================================
    # رسالة Telegram
    # ==================================================

    message = update.get("message")

    if message:

        chat_id = message["chat"]["id"]

        text = message.get(
            "text",
            ""
        ).strip()

        # ==================================================
        # /start
        # ==================================================

        if text == "/start":

            users[chat_id] = {
                "step": "username"
            }

            telegram(
                "sendMessage",
                {
                    "chat_id": chat_id,

                    "text":
                    "👋 أهلاً بك في DarkFollow\n\n"
                    "أرسل الآن اسم مستخدم حسابك في DarkFollow.\n\n"
                    "مثال:\n"
                    "AbuNasser\n\n"
                    "يمكنك أيضاً إرسال:\n"
                    "@AbuNasser"
                }
            )

            return "OK"

        # ==================================================
        # نجاح الدفع
        # ==================================================

        payment = message.get(
            "successful_payment"
        )

        if payment:

            stars = payment[
                "total_amount"
            ]

            payload = payment[
                "invoice_payload"
            ]

            charge_id = payment[
                "telegram_payment_charge_id"
            ]

            # منع تكرار نفس العملية
            if charge_id in processed_payments:

                print(
                    "Payment already processed:",
                    charge_id
                )

                return "OK"

            # قراءة بيانات الفاتورة
            try:

                data = json.loads(
                    payload
                )

                darkfollow_username = data[
                    "darkfollow_username"
                ]

                darkfollow_username = (
                    darkfollow_username
                    .strip()
                    .lstrip("@")
                )

            except Exception as e:

                print(
                    "Payload Error:",
                    e
                )

                telegram(
                    "sendMessage",
                    {
                        "chat_id": chat_id,

                        "text":
                        "❌ حدث خطأ في بيانات عملية الدفع.\n\n"
                        f"رقم العملية:\n{charge_id}"
                    }
                )

                return "OK"

            # حساب الدولار
            dollars = (
                stars /
                STARS_PER_DOLLAR
            )

            # إضافة الرصيد
            result = add_balance(
                darkfollow_username,
                dollars
            )

            print(
                "DarkFollow Result:",
                result
            )

            # إذا نجحت العملية
            if result.get("ok") is True:

                processed_payments.add(
                    charge_id
                )

                telegram(
                    "sendMessage",
                    {
                        "chat_id": chat_id,

                        "text":
                        "✅ تم الدفع بنجاح!\n\n"

                        f"👤 الحساب: "
                        f"@{darkfollow_username}\n"

                        f"⭐ النجوم: "
                        f"{stars}\n"

                        f"💵 المضاف: "
                        f"${dollars:.2f}\n\n"

                        "تمت إضافة الرصيد إلى حساب DarkFollow."
                    }
                )

            else:

                telegram(
                    "sendMessage",
                    {
                        "chat_id": chat_id,

                        "text":
                        "⚠️ تم استلام الدفع، "
                        "لكن تعذر إضافة الرصيد تلقائياً.\n\n"

                        f"👤 الحساب: "
                        f"@{darkfollow_username}\n\n"

                        f"رقم العملية:\n"
                        f"{charge_id}"
                    }
                )

            return "OK"

        # ==================================================
        # إدخال اسم المستخدم
        # ==================================================

        if chat_id in users:

            if users[chat_id].get(
                "step"
            ) == "username":

                username = (
                    text
                    .strip()
                    .lstrip("@")
                )

                # التحقق من الاسم
                if not username:

                    telegram(
                        "sendMessage",
                        {
                            "chat_id": chat_id,

                            "text":
                            "❌ أرسل اسم المستخدم.\n\n"
                            "مثال:\n"
                            "AbuNasser"
                        }
                    )

                    return "OK"

                # التحقق من الأحرف
                if not all(
                    c.isalnum() or c == "_"
                    for c in username
                ):

                    telegram(
                        "sendMessage",
                        {
                            "chat_id": chat_id,

                            "text":
                            "❌ اسم المستخدم غير صحيح.\n\n"
                            "أرسل اسم المستخدم فقط.\n"
                            "مثال:\n"
                            "AbuNasser"
                        }
                    )

                    return "OK"

                # حفظ اسم المستخدم
                users[chat_id] = {
                    "step": "payment",

                    "darkfollow_username":
                    username
                }

                telegram(
                    "sendMessage",
                    {
                        "chat_id": chat_id,

                        "text":
                        "✅ تم حفظ حسابك.\n\n"

                        f"👤 الحساب:\n"
                        f"@{username}\n\n"

                        "اختر مبلغ الشحن:"
                    }
                )

                packages(
                    chat_id
                )

                return "OK"


    # ==================================================
    # ضغط زر الشحن
    # ==================================================

    callback = update.get(
        "callback_query"
    )

    if callback:

        query_id = callback["id"]

        chat_id = callback[
            "message"
        ]["chat"]["id"]

        data = callback.get(
            "data"
        )

        # إغلاق Loading
        telegram(
            "answerCallbackQuery",
            {
                "callback_query_id":
                query_id
            }
        )

        # التأكد من وجود المستخدم
        if chat_id not in users:

            return "OK"

        username = users[
            chat_id
        ].get(
            "darkfollow_username"
        )

        if not username:

            return "OK"

        try:

            stars = int(data)

        except Exception:

            return "OK"

        # إرسال الفاتورة
        result = send_invoice(
            chat_id,
            username,
            stars
        )

        print(
            "Invoice:",
            result
        )

        return "OK"


    # ==================================================
    # Pre Checkout
    # ==================================================

    pre = update.get(
        "pre_checkout_query"
    )

    if pre:

        telegram(
            "answerPreCheckoutQuery",
            {
                "pre_checkout_query_id":
                pre["id"],

                "ok": True
            }
        )

        return "OK"


    return "OK"


# =========================
# Webhook Telegram
# =========================

def set_webhook():

    if not RENDER_URL:

        print(
            "RENDER_EXTERNAL_URL not found"
        )

        return

    webhook_url = (
        f"{RENDER_URL}/webhook"
    )

    result = telegram(
        "setWebhook",
        {
            "url": webhook_url
        }
    )

    print(
        "Webhook:",
        result
    )


# =========================
# تشغيل السيرفر
# =========================

if __name__ == "__main__":

    set_webhook()

    app.run(
        host="0.0.0.0",
        port=PORT
    )
