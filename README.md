<p align="center">
  <img src="https://iili.io/KhN0ztj.png" alt="Logo" width="400"/>
</p>

<p align="center">
  A powerful, self-hosted <b>Google Drive Stremio Media Server</b> built with <b>FastAPI</b>, <b>MongoDB</b>, and <b>Google Drive APIs</b> — seamlessly integrated with <b>Stremio</b> for automated media streaming and discovery.
</p>

> ⚠️ **IMPORTANT NOTE:** Web browsers do not natively support streaming `.mkv` files. To play MKV files seamlessly from Google Drive, **you must use the Stremio Desktop or Mobile App**, which includes built-in libVLC support for MKV decoding.

<p align="center">
  <img src="https://img.shields.io/badge/UV%20Package%20Manager-2B7A77?logo=uv&logoColor=white" alt="UV Package Manager" />
  <img src="https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/MongoDB-47A248?logo=mongodb&logoColor=white" alt="MongoDB" />
  <img src="https://img.shields.io/badge/Google%20Drive-4285F4?logo=googledrive&logoColor=white" alt="Google Drive" />
  <img src="https://img.shields.io/badge/Stremio-8D3DAF?logo=stremio&logoColor=white" alt="Stremio" />
  <img src="https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white" alt="Docker" />
</p>

---

## 🧭 Quick Navigation

- [🚀 Introduction](#-introduction)
  - [✨ Key Features](#-key-features)
  - [💳 Subscription Management](#-subscription-management)
- [⚙️ How It Works](#️-how-it-works)
  - [Overview](#overview)
  - [Behind The Scenes](#behind-the-scenes)
- [🤖 Bot Commands](#-bot-commands)
- [🔧 Configuration Guide](#-configuration-guide)
  - [🧩 Startup Config](#-startup-config)
  - [🗄️ Storage](#️-storage)
  - [🎬 API](#-api)
  - [🌐 Server](#-server)
  - [🔐 Admin Panel](#-admin-panel)
  - [💳 Subscription Management](#-subscription-management-config)
- [🚀 Deployment Guide](#-deployment-guide)
- [📺 Setting up Stremio](#-setting-up-stremio)

# 🚀 Introduction

This project is a **next-generation Google Drive Stremio Media Server** that allows you to **stream your Google Drive files directly through Stremio**, bypassing rate limits and creating your own personal streaming service. It’s designed for **speed, scalability, and reliability**, making it ideal for both personal and community-based media hosting.

## ✨ Key Features

- ⚙️ **Google Drive Backend** — Directly proxy media from Google Drive with full Byte-Range streaming support.
- 🔄 **Automated Sync Engine** — Scans your Google Drive folder recursively and automatically maps files to TMDB/IMDB metadata using PTN parsing.
- 📡 **Admin Telegram Bot** — Upload `token.pickle` dynamically and trigger rescans directly from Telegram without exposing your API.
- 🎬 **Rich Metadata Integration** — Fetches high-quality metadata from TMDB/IMDB.
- 🧠 **Admin Panel Support** — Powerful web-based UI to monitor the server, edit metadata, and manage subscriptions.
- 💳 **Subscription Management** — Robust access control with subscription plans, payment approval workflows, auto token generation, and expiry enforcement.

## ⚙️ How It Works

### Overview

1.  🔐 **Connect Drive:** You send a `token.pickle` (Google OAuth2 token) to the Admin Telegram Bot.
2.  📂 **Scan:** The bot scans the folder ID specified in `config.env` and parses the file names (e.g., `Ghosted 2023 1080p.mkv`).
3.  🧠 **Metadata:** The system looks up TMDB/IMDB and stores the video metadata and `gdrive_file_id` into MongoDB.
4.  🌐 **Stream:** FastAPI serves the Stremio Addon manifest. When you click play in Stremio, the app acts as a highly optimized proxy between Google Drive and Stremio, streaming content instantly.

### Behind The Scenes

| Component | Role |
| :--- | :--- |
| **Google Drive** | Stores the actual `.mkv`, `.mp4` video files. |
| **Telegram Bot** | Acts as an admin interface to upload tokens, check status, and trigger rescans. |
| **MongoDB** | Stores TMDB metadata, Stremio user tokens, and the securely encrypted Google `token.pickle`. |
| **FastAPI** | Hosts REST endpoints for the Stremio Addon (`/manifest.json`, `/catalog`, `/stream`) and proxies video byte streams. |
| **Stremio Addon** | Consumes FastAPI endpoints for catalog display and playback in the Stremio app. |

# 🤖 Bot Commands

Below is the list of available bot commands and their usage within the Telegram bot.

| Command | Description |
| :--- | :--- |
| **`/start`** | (Admin) Upload your `token.pickle`. (User) Get your **Addon URL** for Stremio. |
| **`/scanstatus`** | (Admin) Check how many movies and TV shows are currently indexed from Google Drive. |
| **`/rescan`** | (Admin) Trigger an immediate recursive background scan of your Google Drive folder. |
| **`/log`** | (Admin) Sends the latest **log file** for debugging or monitoring. |
| **`/restart`** | (Admin) Restarts the bot service. |

# 🔧 Configuration Guide

All environment variables for this project are defined in the `config.env` file.

### 🧩 Startup Config

| Variable | Description |
| :--- | :--- |
| **`API_ID`** | Your Telegram **API ID** from [my.telegram.org](https://my.telegram.org). |
| **`API_HASH`** | Your Telegram **API Hash** from [my.telegram.org](https://my.telegram.org). |
| **`BOT_TOKEN`** | The Telegram bot’s **access token** from [@BotFather](https://t.me/BotFather). |
| **`OWNER_ID`** | Your primary **Telegram user ID**. Used for full administrative access. |
| **`ADMIN_TELEGRAM_IDS`** | Comma-separated list of Telegram User IDs who can upload the `token.pickle` and trigger scans. Example: `1234567,9876543` |
| **`GDRIVE_FOLDER_ID`** | The ID of the Google Drive Folder containing your movies and TV shows. |
| **`GDRIVE_SCAN_INTERVAL_HOURS`** | How often the bot automatically rescans the Drive folder for new files (default: `24`). |

### 🗄️ Storage

| Variable | Description |
| :--- | :--- |
| **`DATABASE`** | MongoDB Atlas connection URI(s). You can provide multiple separated by commas for redundancy. <br>Example: `mongodb+srv://user:pass@cluster0.mongodb.net/db1` |

### 🎬 API

| Variable | Description |
| :--- | :--- |
| **`TMDB_API`** | Your **TMDB API key** from [themoviedb.org](https://www.themoviedb.org/settings/api). Used to fetch movie and TV metadata. |

### 🌐 Server

| Variable | Description |
| :--- | :--- |
| **`BASE_URL`** | The Domain URL (e.g. `https://your-domain.com`). Crucial for the Stremio addon setup. |
| **`PORT`** | The port number on which your FastAPI server will run. *Default: `8000`*. |

### 🔐 Admin Panel

| Variable | Description |
| :--- | :--- |
| **`ADMIN_USERNAME`** | Username for logging into the Admin Panel Web UI. |
| **`ADMIN_PASSWORD`** | Password for Admin Panel access.|

### 💳 Subscription Management Config

Enable the subscription feature to gate access to streams behind a paid plan. When `SUBSCRIPTION=True`, every user must have an active subscription to stream content.

| Variable | Description |
| :--- | :--- |
| **`SUBSCRIPTION`** | Enable (`True`) or disable (`False`) the subscription gate. *Default: `False`*. |
| **`SUBSCRIPTION_GROUP_ID`** | Telegram **group/channel ID** where approved subscribers are invited. |
| **`APPROVER_IDS`** | Comma-separated Telegram user IDs of admins who can **approve or reject** subscription payment requests. |
| **`SUBSCRIPTION_URL`** | Telegram bot URL (e.g. `https://t.me/your_bot`) shown to expired users in Stremio so they can renew. |

# 🚀 Deployment Guide

This section explains how to deploy your **GDrive Stremio Media Server** on a VPS using **Docker Compose**.

### 1️⃣ Step 1: Clone & Configure the Project

```bash
git clone https://github.com/weebzone/Telegram-Stremio GDrive-Stremio
cd GDrive-Stremio
mv sample_config.env config.env
nano config.env
```

* Fill in all required variables in `config.env`.
* Press `Ctrl + O`, then `Enter`, then `Ctrl + X` to save and exit.

### 2️⃣ Step 2: Deploy with Docker Compose

```bash
docker compose up -d
```

Your server will now be running at:
➡️ `http://<your-vps-ip>:8000`

### 3️⃣ Step 3: Reverse Proxy with Caddy (For HTTPS)

Stremio addons **require** HTTPS. We recommend using Caddy.

1. **Install Caddy:**
   ```bash
   sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
   curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
   curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
   sudo apt update
   sudo apt install caddy
   ```

2. **Configure Caddy:**
   ```bash
   sudo nano /etc/caddy/Caddyfile
   ```

   Replace contents with:
   ```caddy
   your-domain.com {
       reverse_proxy localhost:8000
   }
   ```

3. **Reload Caddy:**
   ```bash
   sudo systemctl reload caddy
   ```

### 4️⃣ Step 4: Set up Google Drive Credentials

1. Generate a `token.pickle` locally using a Google Cloud Console Desktop application OAuth client.
2. Send the `token.pickle` file to your Telegram Bot as a document.
3. The bot will validate the token, save it securely in MongoDB, and immediately trigger a recursive background scan of your `GDRIVE_FOLDER_ID`.

# 📺 Setting up Stremio

### 📥 Step 1: Download Stremio

Download Stremio for your device:
👉 [https://www.stremio.com/downloads](https://www.stremio.com/downloads)

### 🌐 Step 2: Add the Addon

1.  Open the **Stremio App**.
2.  Go to the **Addon Section** (usually represented by a puzzle piece icon 🧩).
3.  In the search bar, paste your addon URL: `https://<your-domain>/stremio/manifest.json`
    *(If using the Subscription system, get your personal Addon URL from the Telegram Bot via `/start`)*

## 🏅 **Contributor**

|<img width="80" src="https://avatars.githubusercontent.com/u/113664541">|<img width="80" src="https://avatars.githubusercontent.com/u/13152917">|<img width="80" src="https://avatars.githubusercontent.com/u/14957082">|<img width="80" src="https://raw.githubusercontent.com/vflixa1prime/Readme/main/VFlixPRime.png">|
|:---:|:---:|:---:|:---:|
|[`Karan`](https://github.com/Weebzone)|[`Stremio`](https://github.com/Stremio)|[`ChatGPT`](https://github.com/OPENAI)|[`VFlix Prime`](https://t.me/vflixprime2)|
|Author|Stremio SDK|Refactor|Community Support
