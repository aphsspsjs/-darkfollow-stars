import os
import json
import requests
from flask import Flask, request

BOT_TOKEN = os.environ["BOT_TOKEN"]
DARKFOLLOW_TOKEN = os.environ["DARKFOLLOW_TOKEN"]

PORT = int(os.environ.get("PORT", 10000))
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL")

app = Flask(__name__)

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
DARKFOLLOW_API = "https://socpanel.com/privateApi/incrementUserBalance"

# 100 نجمة = 1 دولار
STARS_PER_DOLLAR = 100

users = {}


def telegram(method, data=None):
    r = requests.post(
        f"{TELEGRAM_API}/{method}",
        json=data or {},
        timeout=30
    )
    return r.json()


def add_balance(user_id, amount):
    params = {
        "user_id": int(user_id),
        "amount": int(amount),
        "token": DARKFOLLOW_TOKEN
    }

    r = requests.get(
        DARKFOLLOW_API,
        params=params,
        timeout=30
    )

    try:
        return r.json()
    except Exception:
        return {"ok": False, "response": r.text}


def send_invoice(chat_id, darkfollow_user_id, stars):

    payload = json.dumps({
        "darkfollow_user_id": darkfollow_user_id,
        "stars": stars
    })

    return telegram(
        "sendInvoice",
        {
            "chat_id": chat_id,
            "title": "شحن DarkFollow",
            "description": f"شحن رصيد بقيمة {stars} ⭐",
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


def packages(chat_id):

    keyboard = {
        "inline_keyboard": [
            [{"text": "100 ⭐ = $1", "callback_data": "100"}],
            [{"text": "500 ⭐ = $5", "callback_data": "500"}],
            [{"text": "1000 ⭐ = $10", "callback_data": "1000"}],
            [{"text": "5000 ⭐ = $50", "callback_data": "5000"}]
        ]
    }

    telegram(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": "⭐ اختر مبلغ الشحن:",
            "reply_markup": keyboard
        }
    )


@app.route("/", methods=["GET"])
def home():
    return "DarkFollow Stars Bot is running!"


@app.route("/webhook", methods=["POST"])
def webhook():

    update = request.get_json(silent=True) or {}

    # =========================
    # رسالة
    # =========================

    message = update.get("message")

    if message:

        chat_id = message["chat"]["id"]
        text = message.get("text", "")

        # /start
        if text == "/start":

            users[chat_id] = {
                "step": "user_id"
            }

            telegram(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text":
                    "👋 أهلاً بك في DarkFollow\n\n"
                    "أرسل الآن User ID الخاص بحسابك في DarkFollow."
                }
            )

            return "OK"

        # =========================
        # نجاح الدفع
        # =========================

        payment = message.get("successful_payment")

        if payment:

            stars = payment["total_amount"]
            payload = payment["invoice_payload"]
            charge_id = payment["telegram_payment_charge_id"]

            try:
                data = json.loads(payload)
                darkfollow_user_id = int(
                    data["darkfollow_user_id"]
                )
            except Exception:
                telegram(
                    "sendMessage",
                    {
                        "chat_id": chat_id,
                        "text":
                        "❌ حدث خطأ في بيانات عملية الدفع.\n"
                        f"رقم العملية: {charge_id}"
                    }
                )

                return "OK"

            dollars = stars / STARS_PER_DOLLAR

            result = add_balance(
                darkfollow_user_id,
                dollars
            )

            print("DarkFollow:", result)

            if result.get("ok") is True:

                telegram(
                    "sendMessage",
                    {
                        "chat_id": chat_id,
                        "text":
                        "✅ تم الدفع بنجاح!\n\n"
                        f"⭐ النجوم: {stars}\n"
                        f"💵 المضاف: ${dollars:.2f}\n\n"
                        "تمت إضافة الرصيد إلى حساب DarkFollow."
                    }
                )

            else:

                telegram(
                    "sendMessage",
                    {
                        "chat_id": chat_id,
                        "text":
                        "⚠️ تم استلام الدفع، لكن تعذر إضافة الرصيد تلقائياً.\n\n"
                        f"رقم العملية:\n{charge_id}"
                    }
                )

            return "OK"

        # =========================
        # إدخال DarkFollow User ID
        # =========================

        if chat_id in users:

            if users[chat_id].get("step") == "user_id":

                if not text.isdigit():

                    telegram(
                        "sendMessage",
                        {
                            "chat_id": chat_id,
                            "text":
                            "❌ أرسل User ID رقمي فقط."
                        }
                    )

                    return "OK"

                users[chat_id] = {
                    "step": "payment",
                    "darkfollow_user_id": int(text)
                }

                telegram(
                    "sendMessage",
                    {
                        "chat_id": chat_id,
                        "text":
                        "✅ تم حفظ حسابك.\n\n"
                        "اختر مبلغ الشحن:"
                    }
                )

                packages(chat_id)

                return "OK"

    # =========================
    # ضغط زر الشحن
    # =========================

    callback = update.get("callback_query")

    if callback:

        query_id = callback["id"]
        chat_id = callback["message"]["chat"]["id"]
        data = callback.get("data")

        telegram(
            "answerCallbackQuery",
            {
                "callback_query_id": query_id
            }
        )

        if chat_id not in users:
            return "OK"

        darkfollow_user_id = users[chat_id].get(
            "darkfollow_user_id"
        )

        if not darkfollow_user_id:
            return "OK"

        stars = int(data)

        send_invoice(
            chat_id,
            darkfollow_user_id,
            stars
        )

        return "OK"

    # =========================
    # Pre Checkout
    # =========================

    pre = update.get("pre_checkout_query")

    if pre:

        telegram(
            "answerPreCheckoutQuery",
            {
                "pre_checkout_query_id": pre["id"],
                "ok": True
            }
        )

        return "OK"

    return "OK"


def set_webhook():

    if not RENDER_URL:
        print("RENDER_EXTERNAL_URL not found")
        return

    webhook_url = f"{RENDER_URL}/webhook"

    result = telegram(
        "setWebhook",
        {
            "url": webhook_url
        }
    )

    print("Webhook:", result)


if __name__ == "__main__":

    set_webhook()

    app.run(
        host="0.0.0.0",
        port=PORT
    )
