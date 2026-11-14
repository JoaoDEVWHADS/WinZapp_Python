"""Chat and message routes that were still missing after chats.py: ties together
their three modules (temporary-messages in ephemeral_messages, all-new-messages
and send-status in chat_new, reply-button in chat_interactive).
server.py calls only `register_routes`.
"""
import asyncio
import time

from aiohttp import web

import chat_interactive
import chat_new
import ephemeral_messages


def register_routes(r, *, session, ok, destination_of, quoted_context, publish_status,
                    text_status):
    """Wire the remaining chat routes to the aiohttp router `r`."""

    async def in_thread(func, *args):
        return await asyncio.get_running_loop().run_in_executor(None, func, *args)

    def error(message, status=500):
        return web.json_response({"status": "error", "message": str(message)}, status=status)

    ephemeral_messages.register_routes(r, session=session, ok=ok, error=error,
                                       destination_of=destination_of, in_thread=in_thread,
                                       now=time.time)
    chat_new.register_routes(r, session=session, ok=ok, error=error,
                             publish_status=publish_status, text_status=text_status)
    chat_interactive.register_routes(r, session=session, ok=ok, destination_of=destination_of,
                                     quoted_context=quoted_context)
