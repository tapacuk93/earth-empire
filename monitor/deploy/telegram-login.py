#!/usr/bin/env python3
"""One-time Telegram login for the monitor, run by the owner on the Mac (never on the box, never automated).

    python3 -m venv /tmp/tg && /tmp/tg/bin/pip install telethon boto3
    AWS_REGION=us-east-1 /tmp/tg/bin/python monitor/deploy/telegram-login.py

It reads {"api_id", "api_hash"} from earth-empire/telegram, asks for the phone number, the login code
Telegram sends, and the two-step password if the account has one - all typed here by the owner - and
stores the resulting session string in earth-empire/telegram-session. The box then uses that string to
read public channels only. Nothing is printed or written to disk; run it again if Telegram ends the
session (Settings > Devices shows it as "earth-empire monitor").
"""
import getpass
import json
import os
import sys

import boto3
from telethon.sessions import StringSession
from telethon.sync import TelegramClient

REGION = os.environ.get("AWS_REGION", "us-east-1")
sm = boto3.client("secretsmanager", region_name=REGION)
app = json.loads(sm.get_secret_value(SecretId="earth-empire/telegram")["SecretString"])

client = TelegramClient(StringSession(), int(app["api_id"]), app["api_hash"], device_model="earth-empire monitor")
client.start(phone=lambda: input("Phone number (international, e.g. +380...): ").strip(),
             code_callback=lambda: input("Code Telegram sent: ").strip(),
             password=lambda: getpass.getpass("Two-step password (if set): "))
me = client.get_me()
session = client.session.save()
client.disconnect()

value = json.dumps({"session": session, "user_id": me.id})
try:
    sm.put_secret_value(SecretId="earth-empire/telegram-session", SecretString=value)
except sm.exceptions.ResourceNotFoundException:
    sm.create_secret(Name="earth-empire/telegram-session", SecretString=value,
                     Tags=[{"Key": "project", "Value": "earth-empire"}])
print(f"Saved the session for user id {me.id} to earth-empire/telegram-session.", file=sys.stderr)
