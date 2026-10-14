"""Testes do endpoint de download dos artefatos."""

import json
import zipfile

from fastapi.testclient import TestClient

from app.main import app
from app.services import generation_service

client = TestClient(app)


def _make_job(tmp_path, job_id="abc123", state="completed", with_output=True):
    job_dir = tmp_path / "jobs" / job_id
    job_dir.mkdir(parents=True)
    (job_dir / "job_status.json").write_text(
        json.dumps({"job_id": job_id, "status": state}),
        encoding="utf-8",
    )
    if with_output:
        output = job_dir / "output"
        output.mkdir()
        (output / "README.md").write_text("# Sistema gerado", encoding="utf-8")
        nested = output / "src"
        nested.mkdir()
        (nested / "main.py").write_text("print('ok')", encoding="utf-8")
    return job_dir


def test_download_returns_zip_for_completed_job(tmp_path, monkeypatch):
    job_id = "abc123"
    _make_job(tmp_path, job_id=job_id)
    monkeypatch.setattr(generation_service, "_jobs_root", lambda: tmp_path / "jobs")

    response = client.get(f"/api/generation/{job_id}/download")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/zip")
    assert f'tcc_ia_{job_id}.zip' in response.headers["content-disposition"]

    archive_path = tmp_path / "download.zip"
    archive_path.write_bytes(response.content)
    with zipfile.ZipFile(archive_path) as archive:
        assert set(archive.namelist()) == {"README.md", "src/main.py"}
        assert archive.read("README.md") == b"# Sistema gerado"


def test_download_rejected_while_generation_is_running(tmp_path, monkeypatch):
    _make_job(tmp_path, state="running")
    monkeypatch.setattr(generation_service, "_jobs_root", lambda: tmp_path / "jobs")

    response = client.get("/api/generation/abc123/download")

    assert response.status_code == 409
    assert "concluída" in response.json()["detail"]


def test_download_rejected_when_output_is_empty(tmp_path, monkeypatch):
    _make_job(tmp_path, with_output=False)
    (tmp_path / "jobs" / "abc123" / "output").mkdir()
    monkeypatch.setattr(generation_service, "_jobs_root", lambda: tmp_path / "jobs")

    response = client.get("/api/generation/abc123/download")

    assert response.status_code == 409
    assert "não há arquivos" in response.json()["detail"]


def test_download_returns_404_for_unknown_job(tmp_path, monkeypatch):
    monkeypatch.setattr(generation_service, "_jobs_root", lambda: tmp_path / "jobs")

    response = client.get("/api/generation/abc123/download")

    assert response.status_code == 404
