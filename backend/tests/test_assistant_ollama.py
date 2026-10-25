"""Проверка доступности локального Ollama (Stage 3A) на фейковом сервере."""

from __future__ import annotations

import json

import pytest

from app.assistant.ollama import MAX_RESPONSE_BYTES, OllamaClient, find_model, ModelInfo
from tests.assistant_fakes import MODEL, Route, closed_local_port, fake_ollama, healthy_routes, json_route


def check(url: str, model: str = MODEL, timeout: float = 2.0):
    return OllamaClient(url, timeout).check(model)


class TestAvailable:
    def test_ready_when_server_and_model_present(self):
        with fake_ollama(healthy_routes()) as srv:
            status = check(srv.url)
        assert status.state == "ready" and status.ready
        assert status.server_reachable and status.server_version == "0.40.8"
        assert status.model.name == MODEL
        assert (status.model.parameter_size, status.model.quantization) == ("4.0B", "Q4_K_M")
        assert status.model.remote is False
        # Только чтение: два GET, никаких POST и никаких финансовых данных.
        assert [(m, p) for m, p, _ in srv.requests] == [("GET", "/api/version"), ("GET", "/api/tags")]
        assert all(body == b"" for _, _, body in srv.requests)

    def test_model_without_tag_matches_latest(self):
        models = [{"name": "llama3:latest"}]
        with fake_ollama(healthy_routes(models)) as srv:
            assert check(srv.url, "llama3").state == "ready"
            assert check(srv.url, "llama3:8b").state == "model_not_found"

    def test_system_proxy_is_ignored(self, monkeypatch):
        # Прокси в окружении не должен перехватить локальный запрос.
        for var in ("HTTP_PROXY", "http_proxy", "ALL_PROXY"):
            monkeypatch.setenv(var, "http://10.255.255.1:9")
        monkeypatch.delenv("NO_PROXY", raising=False)
        monkeypatch.delenv("no_proxy", raising=False)
        with fake_ollama(healthy_routes()) as srv:
            assert check(srv.url).state == "ready"


class TestModelProblems:
    def test_model_not_found(self):
        with fake_ollama(healthy_routes([{"name": "gemma3:4b"}])) as srv:
            status = check(srv.url)
        assert status.state == "model_not_found"
        assert status.server_reachable and status.model is None and status.models_found == 1

    def test_no_models_at_all(self):
        with fake_ollama(healthy_routes([])) as srv:
            assert check(srv.url).state == "model_not_found"

    @pytest.mark.parametrize(
        "entry",
        [
            {"name": MODEL, "remote_host": "https://ollama.com:443", "remote_model": "qwen3.5"},
            {"name": "gpt-oss:120b-cloud"},
        ],
    )
    def test_cloud_models_are_not_local(self, entry):
        with fake_ollama(healthy_routes([entry])) as srv:
            status = check(srv.url, entry["name"])
        assert status.state == "model_not_local" and not status.ready


class TestServerProblems:
    def test_nothing_listening(self):
        status = check(f"http://127.0.0.1:{closed_local_port()}")
        assert status.state == "server_unreachable" and not status.server_reachable

    def test_timeout(self):
        routes = healthy_routes()
        routes["/api/version"] = json_route({"version": "0.40.8"}, delay=1.5)
        with fake_ollama(routes) as srv:
            status = check(srv.url, timeout=0.3)
        assert status.state == "server_timeout"

    @pytest.mark.parametrize(
        "route",
        [
            Route(body=b"<html>not ollama</html>", headers={"Content-Type": "text/html"}),  # открытый порт ≠ Ollama
            json_route({"status": "ok"}),  # JSON без версии
            json_route({"version": ""}),
            json_route(["0.40.8"]),
            json_route({"error": "boom"}, status=500),
            Route(body=b"\xff\xfe\x00garbage"),
        ],
        ids=["html", "no-version", "empty-version", "array", "http-500", "not-utf8"],
    )
    def test_bad_version_response(self, route):
        routes = healthy_routes()
        routes["/api/version"] = route
        with fake_ollama(routes) as srv:
            status = check(srv.url)
        assert status.state == "server_bad_response" and not status.ready
        assert [p for _, p, _ in srv.requests] == ["/api/version"]

    def test_redirects_are_not_followed(self):
        # Второй (тоже локальный) сервер — цель перенаправления. Обращений к нему
        # быть не должно: клиент не идёт туда, куда его «пересылают».
        with fake_ollama(healthy_routes()) as target:
            routes = healthy_routes()
            routes["/api/version"] = Route(status=302, body=b"", headers={"Location": f"{target.url}/api/version"})
            with fake_ollama(routes) as srv:
                status = check(srv.url)
        assert status.state == "server_bad_response"
        assert [p for _, p, _ in srv.requests] == ["/api/version"]
        assert target.requests == []

    @pytest.mark.parametrize(
        "payload",
        [{"no_models": []}, {"models": "qwen"}, {"models": [{"size": 1}]}, {"models": [42]}],
    )
    def test_bad_tags_response(self, payload):
        routes = healthy_routes()
        routes["/api/tags"] = json_route(payload)
        with fake_ollama(routes) as srv:
            assert check(srv.url).state == "server_bad_response"

    def test_oversized_response_rejected(self):
        routes = healthy_routes()
        routes["/api/tags"] = Route(body=json.dumps({"models": [], "pad": "x" * (MAX_RESPONSE_BYTES + 10)}).encode())
        with fake_ollama(routes) as srv:
            assert check(srv.url).state == "server_bad_response"


def test_find_model_exact_match_only():
    models = [ModelInfo("qwen3.5:4b", None, None, None, False), ModelInfo("qwen3.5:4b-q4_K_M", None, None, None, False)]
    assert find_model(models, "qwen3.5:4b-q4_K_M").name == "qwen3.5:4b-q4_K_M"
    assert find_model(models, "qwen3.5") is None
