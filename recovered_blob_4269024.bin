import os
import sys
import ssl
import re
import time
import threading
import requests
import uvicorn
from traceback import format_exc
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import Optional
load_dotenv(os.path.join(os.getcwd(), '.env'))
HOST = os.getenv("HOST")
PORT = os.getenv("PORT")
EVOLUTION_HOST = os.getenv("EVOLUTION_HOST")
EVOLUTION_PORT = os.getenv("EVOLUTION_PORT")
APIKEY = os.getenv("APIKEY")
USE_SSL = os.getenv("USE_SSL", "false").lower() == "true"
SSL_CERTFILE = os.getenv("SSL_CERTFILE")
SSL_KEYFILE = os.getenv("SSL_KEYFILE")
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
RATE_LIMIT_MAX_REQUESTS = int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "5"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))
EVOLUTION_SSL_VERIFY = os.getenv("EVOLUTION_SSL_VERIFY", "true").lower() == "true"


app = FastAPI()
_rate_lock = threading.Lock()
_rate_state = {}

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.url.path != "/create_instance/":
        return await call_next(request)

    ip = request.client.host if request.client else "unknown"
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW_SECONDS

    with _rate_lock:
        timestamps = _rate_state.get(ip, [])
        timestamps = [ts for ts in timestamps if ts >= window_start]
        if len(timestamps) >= RATE_LIMIT_MAX_REQUESTS:
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Please try again later."
            )
        timestamps.append(now)
        _rate_state[ip] = timestamps

    return await call_next(request)

@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

class Instance(BaseModel):
    name: str
    number: Optional[str] = None
    token: str

@app.post("/create_instance/")
def create_instance(instance: Instance):
    try:
        result = add_instance(instance.name, instance.number, instance.token)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=502, detail="Failed to connect to Evolution API")
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")

def add_instance(name, number, token):
    url = f"{EVOLUTION_HOST}:{EVOLUTION_PORT}/instance/create"
    payload = {
        "instanceName": name,
        "integration": "WHATSAPP-BAILEYS",
        "token": token,
        "syncFullHistory": False
    }
    if number:
        payload["number"] = number
    headers = {
        "apikey": APIKEY,
        "Content-Type": "application/json"
    }

    response = requests.post(
        url, 
        json=payload, 
        headers=headers, 
        verify=EVOLUTION_SSL_VERIFY,
        timeout=REQUEST_TIMEOUT
    )
    
    if response.status_code not in [200, 201]:
        raise ValueError(f"Evolution API returned status {response.status_code}")
    
    set_websocket_for_instance(token)
    
    # Filter response to only return safe data
    result = response.json()
    safe_response = {
        "success": True,
        "instance": {
            "name": result.get("instance", {}).get("instanceName"),
            "status": result.get("instance", {}).get("status")
        }
    }
    return safe_response


def set_websocket_for_instance(token):
    url = f"{EVOLUTION_HOST}:{EVOLUTION_PORT}/websocket/set/{token}/"
    payload = { "websocket": {
        "enabled": True,
        "events": ["CALL", "APPLICATION_STARTUP", "QRCODE_UPDATED", "MESSAGES_SET", "MESSAGES_UPSERT", "MESSAGES_UPDATE", "MESSAGES_DELETE", "SEND_MESSAGE", "CONTACTS_SET", "CONTACTS_UPSERT", "CONTACTS_UPDATE", "PRESENCE_UPDATE", "CHATS_SET", "CHATS_UPSERT", "CHATS_UPDATE", "CHATS_DELETE", "CONNECTION_UPDATE", "GROUPS_UPSERT", "GROUP_UPDATE", "CALL"]
    } }
    headers = {
        "apikey": APIKEY,
        "Content-Type": "application/json"
    }

    response = requests.post(
        url, 
        json=payload, 
        verify=EVOLUTION_SSL_VERIFY, 
        headers=headers,
        timeout=REQUEST_TIMEOUT
    )

if __name__ == "__main__":
    if USE_SSL:
        uvicorn.run("main:app", host=HOST, port=PORT, ssl_certfile=SSL_CERTFILE, ssl_keyfile=SSL_KEYFILE)
    else:
        uvicorn.run("main:app", host=HOST, port=PORT)
