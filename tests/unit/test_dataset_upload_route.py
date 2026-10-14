"""Testes de contrato da rota de upload."""

from app.main import app


def test_upload_route_is_registered():
    route = next(
        (route for route in app.routes if getattr(route, "path", None) == "/api/datasets/upload"),
        None,
    )
    assert route is not None
    assert "POST" in route.methods


def test_openapi_exposes_upload_operation():
    schema = app.openapi()
    operation = schema["paths"]["/api/datasets/upload"]["post"]
    assert "multipart/form-data" in operation["requestBody"]["content"]
