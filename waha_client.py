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
        # Keep client timeout reasonable (15s max)
        self.client = httpx.AsyncClient(base_url=self.base_url, headers=headers, timeout=15.0)

    async def get_session_status(self) -> str:
        """Returns session status: 'WORKING', 'SCAN_QR_CODE', 'STOPPED', 'STARTING', 'FAILED', etc."""
        try:
            resp = await self.client.get(f"/api/sessions/{self.session}", timeout=5.0)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("status", "UNKNOWN")
            elif resp.status_code == 404:
                return "NOT_FOUND"
        except Exception as e:
            logger.error(f"Error checking WAHA status: {e}")
        return "DISCONNECTED"

    async def restart_session(self) -> bool:
        """Restarts a session that is stuck or in FAILED status"""
        try:
            logger.info(f"Restarting WAHA session '{self.session}'...")
            resp = await self.client.post(f"/api/sessions/{self.session}/restart", timeout=10.0)
            if resp.status_code in [200, 201]:
                logger.info(f"Session '{self.session}' restarted successfully.")
                return True
            else:
                logger.warning(f"Restart returned {resp.status_code}. Attempting stop and start sequence...")
                await self.client.post(f"/api/sessions/{self.session}/stop", timeout=5.0)
                await asyncio.sleep(1)
                resp_start = await self.client.post(f"/api/sessions/{self.session}/start", timeout=5.0)
                return resp_start.status_code in [200, 201]
        except Exception as e:
            logger.error(f"Error restarting WAHA session: {e}")
            return False

    async def logout_session(self) -> bool:
        """Logs out and clears session data so it can be re-paired cleanly"""
        try:
            logger.info(f"Logging out WAHA session '{self.session}'...")
            resp = await self.client.post(f"/api/sessions/{self.session}/logout", timeout=10.0)
            return resp.status_code in [200, 201]
        except Exception as e:
            logger.error(f"Error logging out session: {e}")
            return False

    async def start_session(self) -> bool:
        """Starts or creates the WAHA default session if stopped or not found"""
        try:
            status = await self.get_session_status()
            if status in ["WORKING", "SCAN_QR_CODE"]:
                return True
            
            if status == "FAILED":
                return await self.restart_session()

            if status == "STOPPED":
                logger.info(f"WAHA session '{self.session}' is STOPPED. Calling start...")
                resp = await self.client.post(f"/api/sessions/{self.session}/start", timeout=5.0)
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
                },
                timeout=10.0
            )
            if resp.status_code in [200, 201]:
                logger.info(f"Session '{self.session}' created successfully.")
                return True
            else:
                logger.warning(f"POST /api/sessions returned {resp.status_code}. Attempting restart fallback...")
                return await self.restart_session()
        except Exception as e:
            logger.error(f"Error starting WAHA session: {e}")
            return False

    async def request_pairing_code(self, phone_number: str) -> Tuple[Optional[str], str]:
        """Requests an 8-character phone pairing code for WhatsApp linking without camera QR scan."""
        try:
            clean_phone = "".join(filter(str.isdigit, phone_number))
            if not clean_phone:
                return None, "INVALID_PHONE"

            status = await self.get_session_status()
            if status == "WORKING":
                return None, "WORKING"

            if status in ["FAILED", "STOPPED", "NOT_FOUND", "DISCONNECTED"]:
                logger.info(f"WAHA session is {status}. Restarting before pairing code request...")
                await self.restart_session()
                await asyncio.sleep(2)

            # Wait until session reaches SCAN_QR_CODE or STARTING
            for attempt in range(12):
                status = await self.get_session_status()
                logger.info(f"Waiting for WAHA ready for pairing code ({attempt+1}/12): status={status}")
                if status == "WORKING":
                    return None, "WORKING"
                if status == "SCAN_QR_CODE":
                    break
                if status == "FAILED":
                    await self.restart_session()
                await asyncio.sleep(1.5)

            logger.info(f"Requesting pairing code from WAHA for +{clean_phone}...")
            resp = await self.client.post(
                f"/api/{self.session}/auth/request-code",
                json={"phoneNumber": clean_phone},
                timeout=15.0
            )
            logger.info(f"request-code response status: {resp.status_code}, body: {resp.text[:150]}")
            if resp.status_code in [200, 201]:
                data = resp.json()
                code = data.get("code") or data.get("pairingCode") or data.get("value")
                if code:
                    return str(code), "OK"
                if isinstance(data, str) and len(data) <= 12:
                    return data, "OK"
                return str(data), "OK"
            else:
                logger.error(f"Failed to request pairing code: status {resp.status_code}, {resp.text}")
                return None, f"HTTP_{resp.status_code}"
        except Exception as e:
            logger.error(f"Error in request_pairing_code: {e}")
            return None, "ERROR"

    async def get_qr_image(self) -> Tuple[Optional[bytes], str]:
        """Fetches active QR code as PNG image bytes.
        Fast and non-blocking:
        - If WORKING: returns immediately.
        - Recovers session if FAILED or STOPPED.
        - Polls up to 15 times (~22 seconds) for SCAN_QR_CODE.
        """
        try:
            status = await self.get_session_status()
            if status == "WORKING":
                return None, "WORKING"

            if status in ["FAILED", "STOPPED", "NOT_FOUND", "DISCONNECTED"]:
                logger.info(f"WAHA session is {status}. Initializing/recovering...")
                await self.restart_session()
                await asyncio.sleep(2)

            # Polling loop: up to 15 iterations * 1.5s = ~22 seconds total
            for attempt in range(15):
                status = await self.get_session_status()
                logger.info(f"WAHA QR poll (attempt {attempt+1}/15): status is {status}")

                if status == "WORKING":
                    return None, "WORKING"

                if status == "FAILED":
                    logger.warning("Session entered FAILED status. Triggering restart...")
                    await self.restart_session()
                    await asyncio.sleep(2.0)
                    continue

                if status == "SCAN_QR_CODE":
                    # Status is confirmed ready, fetch image
                    try:
                        resp = await self.client.get(
                            f"/api/{self.session}/auth/qr",
                            headers={"Accept": "image/png"},
                            params={"format": "image"},
                            timeout=6.0
                        )
                        if resp.status_code == 200 and resp.content and len(resp.content) > 100:
                            content_type = resp.headers.get("content-type", "")
                            if "json" in content_type:
                                data = resp.json()
                                b64 = data.get("data") or data.get("qr")
                                if b64:
                                    return base64.b64decode(b64.split(",")[-1]), "SCAN_QR_CODE"
                            return resp.content, "SCAN_QR_CODE"
                    except Exception as err:
                        logger.error(f"Error requesting auth/qr: {err}")

                    # Fallback screenshot endpoint
                    try:
                        resp_screen = await self.client.get(
                            f"/api/screenshot?session={self.session}",
                            timeout=6.0
                        )
                        if resp_screen.status_code == 200 and resp_screen.content and len(resp_screen.content) > 100:
                            return resp_screen.content, "SCAN_QR_CODE"
                    except Exception:
                        pass

                # If STARTING, wait 1.5 seconds
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
                json={"session": self.session, "chatId": chat_id},
                timeout=5.0
            )
        except Exception:
            pass

    async def stop_typing(self, chat_id: str):
        """Stops typing indicator on WhatsApp"""
        try:
            await self.client.post(
                "/api/stopTyping",
                json={"session": self.session, "chatId": chat_id},
                timeout=5.0
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
                },
                timeout=10.0
            )
            return resp.status_code in [200, 201]
        except Exception as e:
            logger.error(f"Failed to send WhatsApp message to {chat_id}: {e}")
            return False

waha = WahaClient()
