"""Testes de contrato das rotas de geração."""

from app.main import app


def test_generation_routes_are_registered():
    paths = {
        getattr(route, "path", None): getattr(route, "methods", set())
        for route in app.routes
    }
    assert "POST" in paths["/api/generation/{job_id}/start"]
    assert "GET" in paths["/api/generation/{job_id}"]


def test_openapi_has_generation_operations():
    schema = app.openapi()
    assert "/api/generation/{job_id}/start" in schema["paths"]
    assert "/api/generation/{job_id}" in schema["paths"]
