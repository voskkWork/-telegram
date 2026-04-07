import html
import logging
import os
import random
import secrets
from typing import Any, Dict, Tuple

from telegram import (
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

BOT_NAME = "Captcha bot"
DEV_CHANNEL_URL = "https://t.me/voskkbots"

logging.basicConfig(level=logging.INFO)

PENDING_KEY = "captcha_pending"
USER_INDEX_KEY = "captcha_index"

JOIN_STATUSES = {"member", "administrator", "restricted"}
LEAVE_STATUSES = {"left", "kicked"}


def no_permissions():
    return ChatPermissions(can_send_messages=False)


def full_permissions():
    return ChatPermissions(can_send_messages=True)


def get_pending(app: Application):
    return app.bot_data.setdefault(PENDING_KEY, {})


def get_user_index(app: Application):
    return app.bot_data.setdefault(USER_INDEX_KEY, {})


def make_challenge():
    a, b = random.randint(1, 20), random.randint(1, 20)
    answer = a + b

    wrong = set()
    while len(wrong) < 2:
        x = answer + random.randint(-5, 5)
        if x != answer:
            wrong.add(x)

    options = [answer, *wrong]
    random.shuffle(options)

    return f"{a} + {b} = ?", answer, options


def keyboard(token, options):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(str(options[0]), callback_data=f"cap:{token}:0"),
        InlineKeyboardButton(str(options[1]), callback_data=f"cap:{token}:1"),
        InlineKeyboardButton(str(options[2]), callback_data=f"cap:{token}:2"),
    ]])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    bot_username = context.bot.username
    link = f"https://t.me/{bot_username}?startgroup=true"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Добавить в чат", url=link)],
        [InlineKeyboardButton("Канал разработчика", url=DEV_CHANNEL_URL)],
    ])

    await update.message.reply_text("Добавь меня в чат", reply_markup=kb)


async def on_new_chat_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    for user in update.message.new_chat_members:
        if user.is_bot:
            continue

        await start_captcha(context, chat_id, user.id, user.mention_html())


async def on_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cm = update.chat_member
    if not cm:
        return

    user = cm.new_chat_member.user

    if user.is_bot:
        return

    if cm.new_chat_member.status in LEAVE_STATUSES:
        await cleanup(context, cm.chat.id, user.id)


async def start_captcha(context, chat_id, user_id, mention):
    pending = get_pending(context.application)
    index = get_user_index(context.application)

    q, ans, opts = make_challenge()
    token = secrets.token_hex(4)

    await context.bot.restrict_chat_member(chat_id, user_id, no_permissions())

    msg = await context.bot.send_message(
        chat_id,
        f"Привет, {mention}\nРеши капчу:\n{q}",
        parse_mode="HTML",
        reply_markup=keyboard(token, opts)
    )

    pending[token] = {
        "chat": chat_id,
        "user": user_id,
        "answer": ans,
        "opts": opts,
        "msg": msg.message_id,
    }
    index[(chat_id, user_id)] = token

    context.job_queue.run_once(timeout, 3600, data={"token": token})


async def timeout(context):
    token = context.job.data["token"]
    pending = get_pending(context.application)

    data = pending.get(token)
    if not data:
        return

    await context.bot.ban_chat_member(data["chat"], data["user"])
    await context.bot.unban_chat_member(data["chat"], data["user"])

    try:
        await context.bot.delete_message(data["chat"], data["msg"])
    except:
        pass

    pending.pop(token, None)


async def cleanup(context, chat_id, user_id):
    index = get_user_index(context.application)
    token = index.get((chat_id, user_id))

    if not token:
        return

    pending = get_pending(context.application)
    data = pending.get(token)

    if not data:
        return

    try:
        await context.bot.delete_message(chat_id, data["msg"])
    except:
        pass

    pending.pop(token, None)


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    _, token, idx = q.data.split(":")
    idx = int(idx)

    pending = get_pending(context.application)
    data = pending.get(token)

    if not data:
        return

    if q.from_user.id != data["user"]:
        return

    if data["opts"][idx] != data["answer"]:
        await q.answer("Неверно", show_alert=True)
        return

    await context.bot.restrict_chat_member(
        data["chat"], data["user"], full_permissions()
    )

    try:
        await context.bot.delete_message(data["chat"], data["msg"])
    except:
        pass

    pending.pop(token, None)


def main():
    app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_chat_members))
    app.add_handler(ChatMemberHandler(on_chat_member, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(CallbackQueryHandler(button, pattern="^cap:"))

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()