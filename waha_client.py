import httpx
import logging
from typing import Optional, Dict, Any
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
        """Returns session status: 'WORKING', 'SCAN_QR_CODE', 'STOPPED', etc."""
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
        """Starts or creates the WAHA default session if stopped"""
        try:
            status = await self.get_session_status()
            if status in ["WORKING", "SCAN_QR_CODE"]:
                return True
            
            # Start or restart session
            resp = await self.client.post(
                "/api/sessions",
                json={
                    "name": self.session,
                    "config": {
                        "webhooks": [
                            {
                                "url": f"http://localhost:{settings.PORT}/api/webhook/waha",
                                "events": ["message", "session.status"]
                            }
                        ]
                    }
                }
            )
            return resp.status_code in [200, 201]
        except Exception as e:
            logger.error(f"Error starting WAHA session: {e}")
            return False

    async def get_qr_image(self) -> Optional[bytes]:
        """Fetches the active QR code as image bytes (PNG)"""
        try:
            # First try the auth/qr endpoint
            resp = await self.client.get(f"/api/{self.session}/auth/qr")
            if resp.status_code == 200 and resp.content:
                return resp.content
            
            # Fallback to screenshot
            resp_screen = await self.client.get(f"/api/screenshot?session={self.session}")
            if resp_screen.status_code == 200 and resp_screen.content:
                return resp_screen.content
        except Exception as e:
            logger.error(f"Error fetching QR code: {e}")
        return None

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
