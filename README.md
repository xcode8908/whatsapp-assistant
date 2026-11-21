# 🤖 WhatsApp AI Assistant & Telegram Controller (Headless & 100% Free)

A self-hosted, headless WhatsApp assistant powered by **WAHA (NOWEB)**, **Google Gemini AI**, and controlled 100% via **Telegram**.

---

## 🌟 Key Features
- **Headless & No Web View:** Zero browser dashboard needed; even the WhatsApp QR code is sent directly to your Telegram!
- **Telegram Master Remote:**
  - 🔴 `/offline` - Turn ON bot to answer WhatsApp messages on your behalf.
  - 🟢 `/online` - Turn OFF bot (Silent mode).
  - `/setmsg <text>` - Set a custom away message (e.g., "Driving right now").
  - `/clearmsg` - Revert back to Gemini AI smart replies.
  - `/schedule <phone> <time> <text>` - Schedule WhatsApp messages!
  - `/qr` - Fetch fresh QR code anytime.
  - `/status` - Check connectivity and current mode.
- **Ghost Mode (Remote Reply):** Incoming WhatsApp messages appear on Telegram with a `[ 💬 Reply ]` button. Reply directly from Telegram without opening WhatsApp!
- **Emergency Priority Siren:** Detects urgent words ("hospital", "urgent", "emergency") and triggers priority alerts.
- **WhatsApp Anti-Ban Protections:**
  - Automatic Group Chat ignoring (only replies to 1-on-1 personal chats).
  - Message Debouncing (bundles multi-part messages sent within 5s into one reply).
  - Spam Cooldown timer (prevents bot-to-bot loops).
  - Human typing delay (2-4 seconds).
- **2-in-1 Single Container:** WAHA and Python backend bundled together to fit 100% inside Render's 750 free hours quota.

---

## 🛠️ Step-by-Step Setup

### Step 1: Telegram Bot Token & Admin ID
1. Open Telegram and search for `@BotFather`.
2. Send `/newbot`, name your bot, and copy the **API Token**.
3. Search for `@userinfobot` on Telegram, press Start, and copy your numeric **Id**.
4. Paste these into `whatsapp_assistant/.env`:
   ```env
   TELEGRAM_BOT_TOKEN=your_token_here
   TELEGRAM_ADMIN_ID=your_numeric_id_here
   ```

### Step 2: Supabase Free PostgreSQL (Recommended for Cloud)
1. Go to [supabase.com](https://supabase.com) and create a free account.
2. Create a new project.
3. Under **Project Settings > Database**, find your **Connection String (URI)**:
   ```
   postgresql://postgres:[YOUR-PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres
   ```
4. Put this in your `.env` or Render Environment Variables as `DATABASE_URL`.
*(Note: If left blank, it will automatically use local SQLite storage).*

---

## 🚀 Deploy to Render (100% Free)

1. Create a new GitHub repository (public or private).
2. Push the `whatsapp_assistant` folder code to GitHub.
3. Log in to [render.com](https://render.com).
4. Click **New + > Web Service** and connect your GitHub repo.
5. Settings:
   - **Environment:** `Docker`
   - **Plan:** `Free`
   - **Health Check Path:** `/health`
6. Add your Environment Variables in Render:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_ADMIN_ID`
   - `GEMINI_API_KEY`
   - `DATABASE_URL` (Supabase connection string)
7. Click **Deploy Web Service**!

---

## ⏰ Step 4: Keep Render Awake (UptimeRobot)
1. Once Render finishes building, copy your live Render URL (e.g., `https://whatsapp-ai-assistant.onrender.com`).
2. Go to [uptimerobot.com](https://uptimerobot.com) (Free).
3. Click **Add New Monitor**:
   - **Monitor Type:** `HTTP(s)`
   - **Friendly Name:** `WhatsApp Bot`
   - **URL:** `https://your-service.onrender.com/health`
   - **Monitoring Interval:** `5 minutes`
4. Save it! Render will now never go to sleep and stay online 24/7.

---

## 📱 How to Pair Your WhatsApp
1. Open your Telegram bot that you created with `@BotFather`.
2. Type `/start`.
3. Click **📱 Scan QR Code** or type `/qr`.
4. The bot will send you the QR code image directly in Telegram!
5. Open WhatsApp on your phone: **Settings > Linked Devices > Link a Device**, and scan the QR code from Telegram.
6. Done! Type `/status` to see `WORKING`.
