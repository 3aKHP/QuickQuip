#!/usr/bin/env python3
"""QuickQuip admin web API — run independently from the bot."""
import os
import uvicorn
from quickquip.app.web.app import create_app
from quickquip.app.web.settings import load_web_env

if __name__ == "__main__":
    load_web_env()
    host = os.environ.get("WEB_ADMIN_HOST", "127.0.0.1")
    port = int(os.environ.get("WEB_ADMIN_PORT", "5104"))
    uvicorn.run(create_app(), host=host, port=port)
