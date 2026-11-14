"""Chats and messages of the bridge: ties together the three modules of the area,
one per topic (reading in chat_listing, sending in chat_sending, actions on
chats in chat_actions). server.py calls only `register_routes`.
"""
import asyncio
import time

from aiohttp import web

import chat_actions
import chat_sending
import chat_listing


def register_routes(r, *, session, ok, wpp_id, destination_of, store_sent, send_media,
                    quoted_context):
    """Wire the chat and message routes to the aiohttp router `r`."""

    async def in_thread(func, *args):
        return await asyncio.get_running_loop().run_in_executor(None, func, *args)

    def error(message, status=500):
        return web.json_response({"status": "error", "message": str(message)}, status=status)

    chat_listing.register_routes(r, session=session, ok=ok, error=error, wpp_id=wpp_id,
                                 now=time.time)
    chat_sending.register_routes(r, session=session, ok=ok, error=error,
                                 destination_of=destination_of, store_sent=store_sent,
                                 send_media=send_media, quoted_context=quoted_context,
                                 in_thread=in_thread)
    chat_actions.register_routes(r, session=session, ok=ok, error=error, in_thread=in_thread)
