"""The bridge's tests never reach the network: catalog_graphql posts with
`requests` unless a test hands it its own `http`, and a route test that goes
through a catalog read would otherwise ask graph.whatsapp.com for real."""
import pytest


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import requests

    def refuse(*args, **kwargs):
        raise requests.ConnectionError("tests do not reach the network")
    monkeypatch.setattr(requests, "post", refuse)
    monkeypatch.setattr(requests, "get", refuse)
