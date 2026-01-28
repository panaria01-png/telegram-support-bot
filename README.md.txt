# Telegram Support Bot (3 departments)

## Features
- Clients write in private to bot
- Choose theme: Sales / Support / Delivery
- Creates ticket number
- Sends card to department group
- Operators reply in group (Reply to card) -> bot sends to client
- One active ticket per client
- Saves history to SQLite
- /chat_id to get group id
- /find to search tickets

## Setup (Windows)
1) Install Python 3.11+
2) Create venv:
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
3) Install deps:
   pip install -r requirements.txt
4) Copy .env.example -> .env and fill
5) Run:
   python main.py