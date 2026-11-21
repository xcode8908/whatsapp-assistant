import asyncio
import base64
import httpx
import logging
from typing import Optional, Dict, Any, Tuple
from config import settings

logger = logging.getLogger(__name__)

class WahaClient:
    def __init__(self):
        self.base_url = settings.WAHA_URL
        self.session = settings.WAHA_SESSION
        self.api_key = settings.WAHA_API_KEY
        headers = {}
        if self.api_key:
            headers["X-Api-Key"] = self.api_key
        self.client = httpx.AsyncClient(base_url=self.base_url, headers=headers, timeout=30.0)

    async def get_session_status(self) -> str:
        """Returns session status: 'WORKING', 'SCAN_QR_CODE', 'STOPPED', 'STARTING', etc."""
        try:
            resp = await self.client.get(f"/api/sessions/{self.session}")
            if resp.status_code == 200:
                data = resp.json()
                return data.get("status", "UNKNOWN")
            elif resp.status_code == 404:
                return "NOT_FOUND"
        except Exception as e:
            logger.error(f"Error checking WAHA status: {e}")
        return "DISCONNECTED"

    async def start_session(self) -> bool:
        """Starts or creates the WAHA default session if stopped or not found"""
        try:
            status = await self.get_session_status()
            if status in ["WORKING", "SCAN_QR_CODE"]:
                return True
            
            if status == "STOPPED":
                logger.info(f"WAHA session '{self.session}' is STOPPED. Calling start...")
                resp = await self.client.post(f"/api/sessions/{self.session}/start")
                return resp.status_code in [200, 201]

            # Create or initialize session
            logger.info(f"Creating WAHA session '{self.session}'...")
            resp = await self.client.post(
                "/api/sessions",
                json={
                    "name": self.session,
                    "config": {
                        "webhooks": [
                            {
                                "url": f"http://127.0.0.1:{settings.PORT}/api/webhook/waha",
                                "events": ["message", "session.status"]
                            }
                        ]
                    }
                }
            )
            if resp.status_code in [200, 201]:
                logger.info(f"Session '{self.session}' created successfully.")
                return True
            else:
                logger.warning(f"POST /api/sessions returned {resp.status_code}. Attempting /start fallback...")
                resp_start = await self.client.post(f"/api/sessions/{self.session}/start")
                return resp_start.status_code in [200, 201]
        except Exception as e:
            logger.error(f"Error starting WAHA session: {e}")
            return False

    async def get_qr_image(self) -> Tuple[Optional[bytes], str]:
        """Fetches the active QR code as image bytes (PNG), auto-starting session and polling if needed"""
        try:
            status = await self.get_session_status()
            if status == "WORKING":
                return None, "WORKING"

            if status in ["NOT_FOUND", "STOPPED", "FAILED", "DISCONNECTED"]:
                logger.info(f"WAHA session is {status}. Auto-starting session '{self.session}'...")
                await self.start_session()
                await asyncio.sleep(2)

            # Poll for QR code ready (up to 8 attempts * 1.5s = ~12 seconds)
            for attempt in range(8):
                status = await self.get_session_status()
                if status == "WORKING":
                    return None, "WORKING"

                # 1. Try auth/qr endpoint with Accept: image/png
                try:
                    resp = await self.client.get(
                        f"/api/{self.session}/auth/qr",
                        headers={"Accept": "image/png"}
                    )
                    if resp.status_code == 200 and resp.content and len(resp.content) > 100:
                        content_type = resp.headers.get("content-type", "")
                        if "json" in content_type:
                            data = resp.json()
                            b64 = data.get("data") or data.get("qr")
                            if b64:
                                return base64.b64decode(b64.split(",")[-1]), "SCAN_QR_CODE"
                        else:
                            return resp.content, "SCAN_QR_CODE"
                except Exception as err:
                    logger.debug(f"auth/qr attempt {attempt+1} error: {err}")

                # 2. Try screenshot endpoint fallback
                try:
                    resp_screen = await self.client.get(f"/api/screenshot?session={self.session}")
                    if resp_screen.status_code == 200 and resp_screen.content and len(resp_screen.content) > 100:
                        return resp_screen.content, "SCAN_QR_CODE"
                except Exception as err:
                    logger.debug(f"screenshot attempt {attempt+1} error: {err}")

                # 3. Try sessions screenshot endpoint
                try:
                    resp_s2 = await self.client.get(f"/api/sessions/{self.session}/screenshot")
                    if resp_s2.status_code == 200 and resp_s2.content and len(resp_s2.content) > 100:
                        return resp_s2.content, "SCAN_QR_CODE"
                except Exception as err:
                    logger.debug(f"sessions screenshot attempt {attempt+1} error: {err}")

                logger.info(f"Waiting for QR code (status: {status}, attempt: {attempt+1}/8)...")
                await asyncio.sleep(1.5)

            return None, status
        except Exception as e:
            logger.error(f"Error fetching QR code: {e}")
            return None, "ERROR"

    async def start_typing(self, chat_id: str):
        """Shows 'typing...' indicator on WhatsApp"""
        try:
            await self.client.post(
                "/api/startTyping",
                json={"session": self.session, "chatId": chat_id}
            )
        except Exception:
            pass

    async def stop_typing(self, chat_id: str):
        """Stops typing indicator on WhatsApp"""
        try:
            await self.client.post(
                "/api/stopTyping",
                json={"session": self.session, "chatId": chat_id}
            )
        except Exception:
            pass

    async def send_text(self, chat_id: str, text: str) -> bool:
        """Sends a text message to a WhatsApp chat_id"""
        try:
            resp = await self.client.post(
                "/api/sendText",
                json={
                    "session": self.session,
                    "chatId": chat_id,
                    "text": text
                }
            )
            return resp.status_code in [200, 201]
        except Exception as e:
            logger.error(f"Failed to send WhatsApp message to {chat_id}: {e}")
            return False

waha = WahaClient()
