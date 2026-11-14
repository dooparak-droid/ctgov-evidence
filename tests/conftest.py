"""Shared fixtures. Any attempt to open a network connection fails the test."""

from __future__ import annotations

import json
import socket
from pathlib import Path

import httpx
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise RuntimeError("Tests must not use the network")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def raw():
    """Single-study fixtures keyed by NCT ID."""
    return {p.stem: json.loads(p.read_text()) for p in FIXTURES.glob("NCT*.json")}


def make_transport(search_pages: list[dict] | None = None, studies: dict | None = None):
    """Mock transport serving saved responses. Records requests on ``.requests``."""
    requests: list[httpx.Request] = []
    pages = list(search_pages or [])
    studies = studies or {}

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if path.endswith("/studies"):
            token = request.url.params.get("pageToken")
            index = 0 if token is None else int(token.removeprefix("page"))
            return httpx.Response(200, json=pages[index])
        nct = path.rsplit("/", 1)[-1]
        if nct in studies:
            return httpx.Response(200, json=studies[nct])
        return httpx.Response(404, json={"message": "not found"})

    transport = httpx.MockTransport(handler)
    transport.requests = requests  # type: ignore[attr-defined]
    return transport


@pytest.fixture
def transport_factory():
    return make_transport
