def test_health_no_auth_required(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "reachable"


def test_health_last_backup_absent_by_default(client):
    body = client.get("/api/health").json()
    assert body["last_backup"] is None


def test_health_reads_last_backup_from_status_file(client, tmp_path, monkeypatch):
    from app.routers import health as health_module

    marker = tmp_path / "last_success"
    marker.write_text("2026-08-15T03:00:00+00:00\n")
    monkeypatch.setattr(health_module, "_LAST_SUCCESS_FILE", marker)

    body = client.get("/api/health").json()
    assert body["last_backup"] == "2026-08-15T03:00:00+00:00"
