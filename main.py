import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, Request
import uvicorn

from config import settings
from database import db
from waha_client import waha
from ai_engine import ai
from telegram_bot import tg_bot

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("whatsapp_assistant")

# Debounce store: {chat_id: {"messages": [...], "task": asyncio.Task}}
pending_debounces: Dict[str, Dict[str, Any]] = {}

def normalize_sender(raw_id: str) -> str:
    """Extracts phone number and formats as clean <phone>@c.us"""
    if not raw_id:
        return ""
    if "@g.us" in raw_id or "@newsletter" in raw_id or "broadcast" in raw_id:
        return raw_id
    clean = raw_id.split("@")[0].split(":")[0]
    digits = "".join(filter(str.isdigit, clean))
    return f"{digits}@c.us" if digits else raw_id

# ==========================================
# Background Scheduler Loop
# ==========================================
async def scheduler_loop():
    logger.info("Starting background scheduler loop...")
    while True:
        try:
            due_items = await db.get_due_schedules()
            for item in due_items:
                chat_id = item["chat_id"]
                message = item["message"]
                schedule_id = item["id"]
                
                logger.info(f"Executing scheduled message #{schedule_id} to {chat_id}")
                success = await waha.send_text(chat_id, message)
                if success:
                    await db.mark_schedule_done(schedule_id, "sent")
                    phone = chat_id.replace("@c.us", "")
                    if tg_bot.app and tg_bot.admin_id:
                        await tg_bot.app.bot.send_message(
                            chat_id=tg_bot.admin_id,
                            text=f"⏰ *Scheduled Message Delivered!*\n\n• To: `+{phone}`\n• Text: _{message}_",
                            parse_mode="Markdown"
                        )
                else:
                    logger.error(f"Failed to deliver scheduled message #{schedule_id}")
        except Exception as e:
            logger.error(f"Error in scheduler loop: {e}")
            
        await asyncio.sleep(15)

# ==========================================
# Message Processing Logic (After Debounce)
# ==========================================
async def process_bundled_message(chat_id: str, bundled_text: str):
    try:
        phone = chat_id.replace("@c.us", "").replace("@s.whatsapp.net", "").replace("@lid", "")
        is_emergency = ai.is_emergency(bundled_text)
        is_offline = await db.is_offline_mode()
        logger.info(f"process_bundled_message: chat_id={chat_id}, phone={phone}, is_offline={is_offline}, is_emergency={is_emergency}")
        
        # 1. Save user incoming message to context
        await db.add_chat_history(chat_id, "user", bundled_text)

        bot_reply_sent: Optional[str] = None

        # 2. Check if bot is OFFLINE and should reply
        if is_offline:
            # Check spam cooldown (emergency bypasses cooldown!)
            can_reply = is_emergency or await db.can_reply(chat_id, settings.COOLDOWN_MINUTES)
            logger.info(f"can_reply check for {chat_id}: {can_reply}")
            
            if can_reply:
                # Show typing indicator
                await waha.start_typing(chat_id)
                await asyncio.sleep(settings.HUMAN_TYPING_DELAY)
                
                # Check for custom message or AI generated
                custom_msg = await db.get_custom_message()
                if custom_msg:
                    reply_text = custom_msg
                    logger.info(f"Using custom message: {reply_text}")
                else:
                    logger.info(f"Calling Gemini AI for reply to {chat_id}...")
                    reply_text = await ai.generate_reply(chat_id, bundled_text)
                    logger.info(f"Gemini AI generated reply: {reply_text}")

                # Stop typing & send reply
                await waha.stop_typing(chat_id)
                logger.info(f"Sending WhatsApp message to {chat_id}: '{reply_text}'")
                sent = await waha.send_text(chat_id, reply_text)
                logger.info(f"waha.send_text result for {chat_id}: {sent}")
                
                if sent:
                    bot_reply_sent = reply_text
                    await db.add_chat_history(chat_id, "model", reply_text)
                    await db.update_cooldown(chat_id)
            else:
                logger.info(f"Cooldown active for {chat_id}. Skipping automated reply to prevent spam.")

        # 3. Notify Admin on Telegram with [ Reply ] button
        logger.info(f"Sending Telegram alert to admin for incoming message from +{phone}...")
        await tg_bot.send_whatsapp_alert(
            sender_phone=phone,
            chat_id=chat_id,
            incoming_message=bundled_text,
            bot_reply=bot_reply_sent,
            is_emergency=is_emergency
        )

    except Exception as e:
        logger.error(f"Error processing bundled message for {chat_id}: {e}", exc_info=True)

# ==========================================
# FastAPI Lifespan (Startup & Shutdown)
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initializing Assistant Services...")
    await db.init()
    
    # Start Telegram Bot Polling
    tg_app = tg_bot.create_application()
    await tg_app.initialize()
    await tg_app.start()
    await tg_app.updater.start_polling()
    logger.info("Telegram Bot polling started successfully.")

    # Start Background Scheduler
    sched_task = asyncio.create_task(scheduler_loop())

    # Proactively ensure WAHA session is initialized in background
    async def init_waha_session():
        for _ in range(15):
            await asyncio.sleep(2)
            try:
                status = await waha.get_session_status()
                if status != "DISCONNECTED":
                    logger.info(f"WAHA reached. Current session status: {status}")
                    if status in ["NOT_FOUND", "STOPPED", "FAILED"]:
                        logger.info(f"Auto-initializing WAHA session '{waha.session}'...")
                        await waha.start_session()
                    break
            except Exception as e:
                logger.debug(f"Waiting for WAHA engine: {e}")

    asyncio.create_task(init_waha_session())

    # Self-healing watchdog: recovers session if it ever enters FAILED or STOPPED
    async def waha_watchdog():
        await asyncio.sleep(45)
        while True:
            try:
                status = await waha.get_session_status()
                if status in ["FAILED", "STOPPED"]:
                    logger.warning(f"Watchdog: WAHA session entered {status}. Automatically recovering session...")
                    await waha.restart_session()
            except Exception as e:
                logger.debug(f"Watchdog check error: {e}")
            await asyncio.sleep(60)

    watchdog_task = asyncio.create_task(waha_watchdog())

    yield

    # Shutdown
    logger.info("Shutting down Assistant Services...")
    sched_task.cancel()
    watchdog_task.cancel()
    if tg_app.updater.running:
        await tg_app.updater.stop()
    await tg_app.stop()
    await tg_app.shutdown()

app = FastAPI(title="WhatsApp Assistant API", lifespan=lifespan)

# ==========================================
# Webhook & Health Endpoints
# ==========================================
@app.get("/")
@app.get("/health")
async def health_check():
    """UptimeRobot ping target"""
    status = await waha.get_session_status()
    is_offline = await db.is_offline_mode()
    return {
        "status": "healthy",
        "waha_status": status,
        "bot_mode": "OFFLINE_ACTIVE" if is_offline else "ONLINE_SILENT"
    }

@app.post("/api/webhook/waha")
async def waha_webhook(request: Request):
    """Receives events from WAHA engine"""
    try:
        body = await request.json()
        event = body.get("event")
        payload = body.get("payload", {})

        # Handle session status change
        if event == "session.status":
            status = payload.get("status")
            logger.info(f"WAHA Session Status Event: {status}")
            if status == "WORKING" and tg_bot.app and tg_bot.admin_id:
                try:
                    await tg_bot.app.bot.send_message(
                        chat_id=tg_bot.admin_id,
                        text=(
                            "🎉 *WhatsApp Linked & Connected Successfully!*\n\n"
                            "Aapka WhatsApp device link ho chuka hai aur bot active hai!\n"
                            "Ab offline mode me bot automatic contextual AI replies dega."
                        ),
                        parse_mode="Markdown"
                    )
                except Exception as err:
                    logger.error(f"Error notifying admin: {err}")
            return {"status": "ok"}

        # Handle incoming message
        if event in ["message", "message.any"]:
            from_me = payload.get("fromMe", False)
            raw_sender = payload.get("from", "")
            raw_to = payload.get("to", "")
            message_text = payload.get("body", "").strip()

            logger.info(f"Incoming WhatsApp webhook: from={raw_sender}, to={raw_to}, fromMe={from_me}, text='{message_text[:60]}'")

            # 1. Strictly ignore WhatsApp Groups, Channels & Broadcasts
            if (
                "@g.us" in raw_sender
                or "@newsletter" in raw_sender
                or "broadcast" in raw_sender
                or payload.get("participant", "").endswith("@g.us")
            ):
                logger.info(f"Ignoring non-private message (group/channel/broadcast): {raw_sender}")
                return {"status": "ignored_group"}

            # 2. Check if message was sent by self to someone else
            sender_clean = raw_sender.split("@")[0].split(":")[0]
            to_clean = raw_to.split("@")[0].split(":")[0]
            if from_me and sender_clean != to_clean:
                logger.info("Ignoring outgoing message sent by user to a contact.")
                return {"status": "ignored_self"}

            # 3. Normalize sender to <phone>@c.us
            sender = normalize_sender(raw_sender)
            if not sender:
                logger.warning(f"Could not parse valid sender from {raw_sender}")
                return {"status": "invalid_sender"}

            if not message_text and payload.get("hasMedia"):
                message_text = "[Attachment: Photo / Audio / Document]"

            if not message_text:
                return {"status": "empty_message"}

            logger.info(f"Queuing 1-on-1 private message from {sender}: '{message_text}'")

            # 4. Debounce / bundling logic (5 seconds)
            if sender not in pending_debounces:
                pending_debounces[sender] = {"messages": [], "task": None}

            pending_debounces[sender]["messages"].append(message_text)

            # Cancel existing debounce timer
            if pending_debounces[sender]["task"] and not pending_debounces[sender]["task"].done():
                pending_debounces[sender]["task"].cancel()

            # Define delayed firing
            async def delayed_fire(chat_id: str):
                await asyncio.sleep(settings.DEBOUNCE_SECONDS)
                data = pending_debounces.pop(chat_id, None)
                if data:
                    bundled = " \n".join(data["messages"])
                    logger.info(f"Firing debounce handler for {chat_id} with {len(data['messages'])} message(s)...")
                    await process_bundled_message(chat_id, bundled)

            pending_debounces[sender]["task"] = asyncio.create_task(delayed_fire(sender))
            return {"status": "debouncing"}

    except Exception as e:
        logger.error(f"Error handling WAHA webhook: {e}", exc_info=True)

    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=settings.PORT, reload=False)
