#!/usr/bin/env python3
"""QuickQuip admin web API — run independently from the bot."""
import uvicorn
from quickquip.app.web.app import create_app
from quickquip.app.web.settings import get_web_admin_host, get_web_admin_port

if __name__ == "__main__":
    uvicorn.run(create_app(), host=get_web_admin_host(), port=get_web_admin_port())
