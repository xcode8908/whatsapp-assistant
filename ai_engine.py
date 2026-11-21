import httpx
import logging
from typing import List, Dict, Tuple
from config import settings
from database import db

logger = logging.getLogger(__name__)

EMERGENCY_KEYWORDS = [
    "emergency", "urgent", "hospital", "accident", "zaroori", 
    "zaruri", "danger", "immediately", "call me", "fast", "jaldi",
    "help", "madad", "police", "ambulance", "attack", "blood"
]

SYSTEM_PROMPT = """You are a smart, polite, and helpful Personal AI Assistant for Sir Lipan.
Sir is currently OFFLINE / busy.

Your job:
1. Speak in a natural, polite Hinglish (mix of Hindi & English) or English depending on how the person speaks.
2. Tell them respectfully that Sir is offline right now.
3. If they haven't introduced themselves, politely ask their name and the purpose of their message.
4. Assure them that you have noted their message and Sir will contact them as soon as he is back online.
5. KEEP YOUR REPLY VERY SHORT (Maximum 1 to 2 sentences). Do not write essays or overly robotic corporate disclaimers.
6. Never make promises or commitments on Sir's behalf.
"""

class AIEngine:
    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        # Using Gemini 1.5 Flash (fast, lightweight, generous free tier)
        self.endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={self.api_key}"

    def is_emergency(self, text: str) -> bool:
        """Checks if the message indicates an urgent or emergency situation"""
        lower = text.lower()
        return any(keyword in lower for keyword in EMERGENCY_KEYWORDS)

    async def generate_reply(self, chat_id: str, new_message: str) -> str:
        """Generates a smart contextual reply using Gemini API"""
        if not self.api_key:
            return "Hello! Main Sir ka assistant hoon. Sir abhi offline hain, thodi der mein update denge."

        try:
            # 1. Fetch recent history for context
            history = await db.get_recent_history(chat_id, limit=4)
            
            # Format contents for Gemini REST API
            contents = []
            
            # Add past context
            for item in history:
                role = "user" if item["role"] == "user" else "model"
                contents.append({
                    "role": role,
                    "parts": [{"text": item["text"]}]
                })
            
            # Add current user message
            contents.append({
                "role": "user",
                "parts": [{"text": new_message}]
            })

            payload = {
                "system_instruction": {
                    "parts": [{"text": SYSTEM_PROMPT}]
                },
                "contents": contents,
                "generationConfig": {
                    "temperature": 0.7,
                    "maxOutputTokens": 100
                }
            }

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(self.endpoint, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        reply_text = candidates[0]["content"]["parts"][0]["text"].strip()
                        return reply_text
                else:
                    logger.error(f"Gemini API returned error: {resp.status_code} - {resp.text}")

        except Exception as e:
            logger.error(f"Error generating AI reply: {e}")

        # Fallback response
        return "Hello! Sir abhi offline hain. Maine aapka message note kar liya hai, aate hi wo aapse contact karenge."

ai = AIEngine()
