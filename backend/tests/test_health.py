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


def test_health_last_offsite_backup_absent_by_default(client):
    body = client.get("/api/health").json()
    assert body["last_offsite_backup"] is None


def test_health_reads_last_offsite_backup_from_status_file(client, tmp_path, monkeypatch):
    from app.routers import health as health_module

    marker = tmp_path / "last_offsite_success"
    marker.write_text("2026-08-20T03:04:00+00:00\n")
    monkeypatch.setattr(health_module, "_LAST_OFFSITE_FILE", marker)

    body = client.get("/api/health").json()
    assert body["last_offsite_backup"] == "2026-08-20T03:04:00+00:00"


def test_health_reports_the_two_backup_legs_independently(client, tmp_path, monkeypatch):
    # ADR 0015: a NAS that is asleep must not make /api/health report that
    # there is no backup at all when the local one succeeded.
    from app.routers import health as health_module

    local = tmp_path / "last_success"
    local.write_text("2026-08-22T03:00:00+00:00\n")
    monkeypatch.setattr(health_module, "_LAST_SUCCESS_FILE", local)
    monkeypatch.setattr(health_module, "_LAST_OFFSITE_FILE", tmp_path / "never-written")

    body = client.get("/api/health").json()
    assert body["last_backup"] == "2026-08-22T03:00:00+00:00"
    assert body["last_offsite_backup"] is None
    assert body["status"] == "ok"
