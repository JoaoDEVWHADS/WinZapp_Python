"""Wires the commerce routes: business accounts and catalogs (business.py),
carts (commerce_cart.py), orders (commerce_orders.py), a business's own
catalog and profile (catalog_admin.py) and the interactive and commerce
messages (interactive_send.py). server.py calls only `register_routes`.
"""
import business
import catalog_admin
import commerce_cart
import commerce_orders
import interactive_send


def register_routes(r, *, session, ok, jid_from_text, jid_text, destination_of, store_sent,
                    quoted_context):
    """Wire the commerce routes to the aiohttp router `r`."""
    business.register_routes(r, session=session, ok=ok, jid_from_text=jid_from_text,
                             jid_text=jid_text)
    commerce_cart.register_routes(r, session=session, jid_from_text=jid_from_text,
                                  jid_text=jid_text, destination_of=destination_of,
                                  store_sent=store_sent)
    commerce_orders.register_routes(r, session=session, jid_from_text=jid_from_text,
                                    jid_text=jid_text, destination_of=destination_of,
                                    store_sent=store_sent, quoted_context=quoted_context)
    catalog_admin.register_routes(r, session=session, jid_from_text=jid_from_text,
                                  jid_text=jid_text)
    interactive_send.register_routes(r, session=session, destination_of=destination_of,
                                     store_sent=store_sent, jid_from_text=jid_from_text)
