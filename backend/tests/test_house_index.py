def test_upsert_and_list_index_points(client, auth_headers):
    create = client.post(
        "/api/house-index",
        json={"series": "bavaria-rural", "date": "2024-01-01", "index_value": "110.5"},
        headers=auth_headers,
    )
    assert create.status_code == 201

    update = client.post(
        "/api/house-index",
        json={"series": "bavaria-rural", "date": "2024-01-01", "index_value": "111.0"},
        headers=auth_headers,
    )
    assert update.status_code == 201
    assert update.json()["index_value"] == "111.0"

    listed = client.get(
        "/api/house-index", params={"series": "bavaria-rural"}, headers=auth_headers
    )
    assert len(listed.json()) == 1  # upsert, not a duplicate row
