import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from config import settings
from database import db
from waha_client import waha

logger = logging.getLogger(__name__)

# In-memory state for Telegram Reply mode: {admin_chat_id: target_whatsapp_chat_id}
admin_reply_targets: Dict[int, str] = {}

class TelegramBotManager:
    def __init__(self):
        self.token = settings.TELEGRAM_BOT_TOKEN
        self.admin_id = settings.TELEGRAM_ADMIN_ID
        self.app: Optional[Application] = None

    def is_admin(self, user_id: int) -> bool:
        if not self.admin_id or self.admin_id == 0:
            self.admin_id = user_id
            logger.info(f"Auto-bound admin ID to active user: {user_id}")
            return True
        return user_id == self.admin_id

    def build_main_keyboard(self, is_offline: bool) -> InlineKeyboardMarkup:
        toggle_btn = (
            InlineKeyboardButton("🟢 Switch to ONLINE", callback_data="set_online")
            if is_offline
            else InlineKeyboardButton("🔴 Switch to OFFLINE", callback_data="set_offline")
        )
        keyboard = [
            [toggle_btn],
            [
                InlineKeyboardButton("📱 Scan QR Code", callback_data="get_qr"),
                InlineKeyboardButton("📊 Status", callback_data="get_status")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)

    # ==========================================
    # Command Handlers
    # ==========================================
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        logger.info(f"User ID {user_id} triggered /start. (Configured Admin: {self.admin_id})")
        
        if not self.is_admin(user_id):
            await update.message.reply_text(
                f"⛔ *Unauthorized Access!*\n\n"
                f"Your actual Telegram User ID is: `{user_id}`\n"
                f"Configured Admin ID is: `{self.admin_id}`\n\n"
                f"Please reply with this ID so it can be set as Admin!",
                parse_mode="Markdown"
            )
            return

        is_offline = await db.is_offline_mode()
        custom_msg = await db.get_custom_message()
        mode_text = "🔴 *OFFLINE (Bot Active)*" if is_offline else "🟢 *ONLINE (Bot Silent)*"
        reply_mode = f"Custom: _{custom_msg}_" if custom_msg else "🧠 *Smart AI (Gemini)*"

        text = (
            "👋 *Welcome to your WhatsApp Assistant Controller!*\n\n"
            f"• Current Mode: {mode_text}\n"
            f"• Auto-Reply Mode: {reply_mode}\n\n"
            "Use the buttons below or commands:\n"
            "• `/offline` - Turn ON auto-reply\n"
            "• `/online` - Turn OFF auto-reply\n"
            "• `/setmsg <text>` - Set custom reply\n"
            "• `/clearmsg` - Use Smart AI reply\n"
            "• `/schedule <number> <HH:MM> <text>` - Schedule message\n"
            "• `/qr` - Get WhatsApp QR Code\n"
            "• `/status` - Check connectivity"
        )
        await update.message.reply_text(
            text,
            reply_markup=self.build_main_keyboard(is_offline),
            parse_mode="Markdown"
        )

    async def cmd_offline(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id): return
        await db.set_offline_mode(True)
        await update.message.reply_text(
            "🔴 *Offline Mode is ON!*\nBot is now actively replying to WhatsApp messages on your behalf.",
            reply_markup=self.build_main_keyboard(True),
            parse_mode="Markdown"
        )

    async def cmd_online(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id): return
        await db.set_offline_mode(False)
        await update.message.reply_text(
            "🟢 *Online Mode is ON!*\nBot is now silent. You have full manual control on WhatsApp.",
            reply_markup=self.build_main_keyboard(False),
            parse_mode="Markdown"
        )

    async def cmd_setmsg(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id): return
        if not context.args:
            await update.message.reply_text("❌ Please provide message text.\nExample:\n`/setmsg Main abhi drive kar raha hu, 2 baje reply karunga.`", parse_mode="Markdown")
            return

        msg_text = " ".join(context.args)
        await db.set_custom_message(msg_text)
        await update.message.reply_text(
            f"✅ *Custom Reply Set!*\n\n_{msg_text}_\n\n(To switch back to Gemini AI, use `/clearmsg`)",
            parse_mode="Markdown"
        )

    async def cmd_clearmsg(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id): return
        await db.set_custom_message(None)
        await update.message.reply_text("🧠 *Smart AI Mode Restored!*\nBot will now use Gemini AI to generate contextual replies.")

    async def cmd_qr(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id): return
        msg = await update.message.reply_text("⏳ Generating WhatsApp QR Code... Please wait a few seconds.")
        
        qr_bytes, status = await waha.get_qr_image()
        if qr_bytes:
            await update.message.reply_photo(
                photo=qr_bytes,
                caption=(
                    "📱 *Scan this QR Code in WhatsApp:*\n\n"
                    "1. Open WhatsApp on your phone\n"
                    "2. Go to **Settings > Linked Devices**\n"
                    "3. Tap **Link a Device** and scan this QR code\n\n"
                    "*(Code is live. Scan promptly!)*"
                ),
                parse_mode="Markdown"
            )
            try:
                await msg.delete()
            except Exception:
                pass
        elif status == "WORKING":
            await msg.edit_text("✅ WhatsApp is already connected and **WORKING**! No QR scan needed.", parse_mode="Markdown")
        else:
            await msg.edit_text(f"⚠️ Could not fetch QR yet. Session status: `{status}`.\nPlease retry with /qr in 5-10 seconds.", parse_mode="Markdown")

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id): return
        status = await waha.get_session_status()
        is_offline = await db.is_offline_mode()
        custom_msg = await db.get_custom_message()

        status_emoji = "✅" if status == "WORKING" else "⚠️"
        mode_text = "🔴 OFFLINE (Auto-Reply ACTIVE)" if is_offline else "🟢 ONLINE (Bot SILENT)"
        reply_mode = f"Custom Text: '{custom_msg}'" if custom_msg else "Smart AI (Gemini 1.5 Flash)"

        report = (
            f"📊 *System Status Report*\n\n"
            f"• WhatsApp Connection: {status_emoji} `{status}`\n"
            f"• Current State: *{mode_text}*\n"
            f"• Auto-Responder: *{reply_mode}*\n"
            f"• Server Engine: `WAHA NOWEB`"
        )
        await update.message.reply_text(
            report,
            reply_markup=self.build_main_keyboard(is_offline),
            parse_mode="Markdown"
        )

    async def cmd_schedule(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id): return
        
        # Expected: /schedule <number> <time_e.g._14:30_or_10:00AM> <message>
        if len(context.args) < 3:
            await update.message.reply_text(
                "❌ *Invalid format!*\nUsage:\n`/schedule <number> <time> <message>`\n\nExample:\n`/schedule 919876543210 14:30 Meeting fixed hai!`\n`/schedule 919876543210 10:00AM Happy Birthday!`",
                parse_mode="Markdown"
            )
            return

        raw_phone = context.args[0].replace("+", "").strip()
        time_str = context.args[1].strip()
        msg_text = " ".join(context.args[2:]).strip()

        # Format WhatsApp chatId
        chat_id = f"{raw_phone}@c.us" if "@" not in raw_phone else raw_phone

        # Parse time (assumed Indian Standard Time / UTC+5:30)
        try:
            # Match 24-hr (14:30) or 12-hr (10:00AM)
            now_utc = datetime.now(timezone.utc)
            # IST offset is +5:30
            ist_offset = timedelta(hours=5, minutes=30)
            now_ist = now_utc + ist_offset

            target_hour = 0
            target_minute = 0

            time_clean = time_str.upper()
            if "AM" in time_clean or "PM" in time_clean:
                parsed_time = datetime.strptime(time_clean, "%I:%M%p")
                target_hour, target_minute = parsed_time.hour, parsed_time.minute
            else:
                parsed_time = datetime.strptime(time_clean, "%H:%M")
                target_hour, target_minute = parsed_time.hour, parsed_time.minute

            # Build target IST datetime for today
            sched_ist = now_ist.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
            # If time has already passed today, schedule for tomorrow
            if sched_ist <= now_ist:
                sched_ist += timedelta(days=1)

            # Convert back to epoch timestamp
            sched_epoch = int((sched_ist - ist_offset).replace(tzinfo=timezone.utc).timestamp())

            await db.add_schedule(chat_id, msg_text, sched_epoch)
            
            await update.message.reply_text(
                f"⏰ *Message Scheduled Successfully!*\n\n"
                f"• Target: `+{raw_phone}`\n"
                f"• Scheduled Time: `{sched_ist.strftime('%d-%b-%Y %I:%M %p')} IST`\n"
                f"• Message: _{msg_text}_",
                parse_mode="Markdown"
            )

        except Exception as e:
            await update.message.reply_text(f"❌ Failed to parse time '{time_str}'. Please use format like `14:30` or `10:00AM`.")

    # ==========================================
    # Button Callbacks & Ghost Mode Relay
    # ==========================================
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        if not self.is_admin(query.from_user.id): return
        data = query.data

        if data == "set_offline":
            await db.set_offline_mode(True)
            await query.edit_message_text(
                "🔴 *Switched to OFFLINE Mode!*\nBot is now answering WhatsApp messages.",
                reply_markup=self.build_main_keyboard(True),
                parse_mode="Markdown"
            )
        elif data == "set_online":
            await db.set_offline_mode(False)
            await query.edit_message_text(
                "🟢 *Switched to ONLINE Mode!*\nBot is now silent.",
                reply_markup=self.build_main_keyboard(False),
                parse_mode="Markdown"
            )
        elif data == "get_qr":
            msg = await query.message.reply_text("⏳ Generating WhatsApp QR Code... Please wait a few seconds.")
            qr_bytes, status = await waha.get_qr_image()
            if qr_bytes:
                await query.message.reply_photo(
                    photo=qr_bytes,
                    caption=(
                        "📱 *Scan this QR Code in WhatsApp:*\n\n"
                        "1. Open WhatsApp on your phone\n"
                        "2. Go to **Settings > Linked Devices**\n"
                        "3. Tap **Link a Device** and scan this QR code\n\n"
                        "*(Code is live. Scan promptly!)*"
                    ),
                    parse_mode="Markdown"
                )
                try:
                    await msg.delete()
                except Exception:
                    pass
            elif status == "WORKING":
                await msg.edit_text("✅ WhatsApp is already connected and **WORKING**! No QR scan needed.", parse_mode="Markdown")
            else:
                await msg.edit_text(f"⚠️ Could not fetch QR yet. Session status: `{status}`.\nPlease retry in 5-10 seconds.", parse_mode="Markdown")
        elif data == "get_status":
            status = await waha.get_session_status()
            is_offline = await db.is_offline_mode()
            mode_text = "🔴 OFFLINE" if is_offline else "🟢 ONLINE"
            await query.message.reply_text(
                f"📊 Status: `{status}` | Mode: *{mode_text}*",
                reply_markup=self.build_main_keyboard(is_offline),
                parse_mode="Markdown"
            )
        elif data.startswith("reply:"):
            # Set target for remote reply
            target_chat_id = data.split(":", 1)[1]
            admin_reply_targets[query.from_user.id] = target_chat_id
            phone = target_chat_id.replace("@c.us", "")
            await query.message.reply_text(
                f"✍️ *Ghost Reply Mode Active for +{phone}*\n\nType your reply below and send. It will be delivered directly to their WhatsApp!",
                parse_mode="Markdown"
            )

    async def handle_admin_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handles replies from the admin back into WhatsApp"""
        if not self.is_admin(update.effective_user.id): return
        admin_id = update.effective_user.id

        # 1. Check if user is replying to a target set via [ Reply ] button
        target_chat = admin_reply_targets.get(admin_id)

        # 2. Or check if user natively quoted/replied to an alert message
        if not target_chat and update.message.reply_to_message:
            quoted_text = update.message.reply_to_message.text or ""
            # Search for @c.us or +phone pattern in the quoted alert
            match = re.search(r"\((\d+)@c\.us\)", quoted_text) or re.search(r"\+(\d+)", quoted_text)
            if match:
                target_chat = f"{match.group(1)}@c.us"

        if target_chat:
            reply_text = update.message.text
            success = await waha.send_text(target_chat, reply_text)
            phone = target_chat.replace("@c.us", "")
            if success:
                # Save into history
                await db.add_chat_history(target_chat, "model", reply_text)
                await update.message.reply_text(f"✅ *Delivered to WhatsApp (+{phone})!*", parse_mode="Markdown")
            else:
                await update.message.reply_text(f"❌ *Failed to deliver to +{phone}*. Check WhatsApp status.")
            
            # Clear pending target
            admin_reply_targets.pop(admin_id, None)

    # ==========================================
    # Outgoing Alert to Admin Telegram
    # ==========================================
    async def send_whatsapp_alert(
        self,
        sender_phone: str,
        chat_id: str,
        incoming_message: str,
        bot_reply: Optional[str] = None,
        is_emergency: bool = False
    ):
        """Sends live WhatsApp alert to Admin Telegram with a [ Reply ] button"""
        if not self.app or not self.admin_id:
            return

        header = "🚨 *EMERGENCY / URGENT ALERT!*" if is_emergency else "💬 *New WhatsApp Message*"
        reply_info = f"\n🤖 *Bot Replied:* _{bot_reply}_" if bot_reply else "\n*(Bot is Online / Silent - No reply sent)*"

        text = (
            f"{header}\n\n"
            f"👤 *From:* `+{sender_phone}` (`{chat_id}`)\n"
            f"📩 *Message:* {incoming_message}"
            f"{reply_info}"
        )

        reply_btn = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"💬 Reply to +{sender_phone}", callback_data=f"reply:{chat_id}")]
        ])

        try:
            await self.app.bot.send_message(
                chat_id=self.admin_id,
                text=text,
                reply_markup=reply_btn,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}")

    def create_application(self) -> Application:
        """Configures and returns the python-telegram-bot application"""
        self.app = Application.builder().token(self.token).build()

        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("offline", self.cmd_offline))
        self.app.add_handler(CommandHandler("online", self.cmd_online))
        self.app.add_handler(CommandHandler("setmsg", self.cmd_setmsg))
        self.app.add_handler(CommandHandler("clearmsg", self.cmd_clearmsg))
        self.app.add_handler(CommandHandler("qr", self.cmd_qr))
        self.app.add_handler(CommandHandler("status", self.cmd_status))
        self.app.add_handler(CommandHandler("schedule", self.cmd_schedule))
        
        self.app.add_handler(CallbackQueryHandler(self.handle_callback))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_admin_message))

        return self.app

tg_bot = TelegramBotManager()
