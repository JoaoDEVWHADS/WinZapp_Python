"""Tests for automatic stale socket retry in api_client."""

import pytest
import requests
from unittest.mock import MagicMock
from core.api_client import api_request


def test_api_request_retries_on_stale_socket(monkeypatch):
    calls = []

    def mock_post(url, headers=None, timeout=None, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            # First attempt fails with dropped connection on stale pool
            raise requests.exceptions.ConnectionError("('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))")
        # Second attempt succeeds
        resp = MagicMock()
        resp.status_code = 201
        return resp

    monkeypatch.setattr("requests.post", mock_post)

    response = api_request("POST", "http://127.0.0.1:6300/api/tok/send-reply", token="tok")
    assert response.status_code == 201
    assert len(calls) == 2
