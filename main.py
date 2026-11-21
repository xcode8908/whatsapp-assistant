import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Dict, Any, List
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import JSONResponse
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
        phone = chat_id.replace("@c.us", "")
        is_emergency = ai.is_emergency(bundled_text)
        is_offline = await db.is_offline_mode()
        
        # 1. Save user incoming message to context
        await db.add_chat_history(chat_id, "user", bundled_text)

        bot_reply_sent: Optional[str] = None

        # 2. Check if bot is OFFLINE and should reply
        if is_offline:
            # Check spam cooldown
            can_reply = await db.can_reply(chat_id, settings.COOLDOWN_MINUTES)
            
            if can_reply:
                # Show typing indicator
                await waha.start_typing(chat_id)
                await asyncio.sleep(settings.HUMAN_TYPING_DELAY)
                
                # Check for custom message or AI generated
                custom_msg = await db.get_custom_message()
                if custom_msg:
                    reply_text = custom_msg
                else:
                    reply_text = await ai.generate_reply(chat_id, bundled_text)

                # Stop typing & send reply
                await waha.stop_typing(chat_id)
                sent = await waha.send_text(chat_id, reply_text)
                
                if sent:
                    bot_reply_sent = reply_text
                    await db.add_chat_history(chat_id, "model", reply_text)
                    await db.update_cooldown(chat_id)
            else:
                logger.info(f"Cooldown active for {chat_id}. Skipping automated reply to prevent spam.")

        # 3. Notify Admin on Telegram with [ Reply ] button
        await tg_bot.send_whatsapp_alert(
            sender_phone=phone,
            chat_id=chat_id,
            incoming_message=bundled_text,
            bot_reply=bot_reply_sent,
            is_emergency=is_emergency
        )

    except Exception as e:
        logger.error(f"Error processing bundled message for {chat_id}: {e}")

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

    yield

    # Shutdown
    logger.info("Shutting down Assistant Services...")
    sched_task.cancel()
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

        # Handle session QR state change
        if event == "session.status":
            status = payload.get("status")
            logger.info(f"WAHA Session Status Event: {status}")
            return {"status": "ok"}

        # Handle incoming message
        if event == "message":
            # 1. Ignore messages sent by self
            if payload.get("fromMe"):
                return {"status": "ignored_self"}

            sender = payload.get("from", "")

            # 2. STRICT GROUP FILTER: Ignore WhatsApp Groups!
            if sender.endswith("@g.us") or sender == "status@broadcast":
                return {"status": "ignored_group"}

            # Only handle 1-on-1 private chats
            if not sender.endswith("@c.us"):
                return {"status": "ignored_non_user"}

            message_text = payload.get("body", "").strip()
            if not message_text and payload.get("hasMedia"):
                message_text = "[Attachment: Photo / Audio / Document]"

            if not message_text:
                return {"status": "empty_message"}

            # 3. Message Debounce / Bundling logic (5 seconds)
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
                    await process_bundled_message(chat_id, bundled)

            pending_debounces[sender]["task"] = asyncio.create_task(delayed_fire(sender))
            return {"status": "debouncing"}

    except Exception as e:
        logger.error(f"Error handling WAHA webhook: {e}")

    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=settings.PORT, reload=False)
