from fastapi.testclient import TestClient

from app.main import app


def _assert_error(response, status_code: int) -> None:
    assert response.status_code == status_code
    body = response.json()
    assert set(body) == {"detail"}
    assert set(body["detail"]) == {"code", "message"}
    assert body["detail"]["code"]
    assert body["detail"]["message"]


def test_c008_openapi_paths_handlers_and_error_contract() -> None:
    openapi = app.openapi()
    expected_paths = {
        "/api/episodes/{episode_id}/clips/preview",
        "/api/episodes/{episode_id}/clips",
        "/api/clips/{clip_id}",
        "/api/clips/{clip_id}/slots",
        "/api/clips/{clip_id}/slots/{slot_no}",
        "/media/slot-overrides/{slot_id}",
    }
    clip_slot_paths = {
        path
        for path in openapi["paths"]
        if "/clips" in path or "slot" in path
    }
    assert clip_slot_paths == expected_paths
    assert sorted(app.state.task_handlers) == [
        "gen_asset_image",
        "gen_assets",
        "gen_shots",
    ]
    assert all(
        "gen_clip_video" not in path and "minimax" not in path.lower()
        for path in openapi["paths"]
    )

    slot_patch = openapi["paths"]["/api/clips/{clip_id}/slots/{slot_no}"]["patch"]
    request_body = slot_patch["requestBody"]
    assert set(request_body["content"]) == {
        "application/json",
        "multipart/form-data",
    }
    assert request_body["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ClipSlotEnabledPatch"
    }
    multipart_schema = request_body["content"]["multipart/form-data"]["schema"]
    assert len(multipart_schema["oneOf"]) == 2
    assert multipart_schema["oneOf"][0]["required"] == ["file"]
    assert multipart_schema["oneOf"][1]["required"] == ["clear_override"]
    media_response = openapi["paths"]["/media/slot-overrides/{slot_id}"]["get"]
    assert "content" not in media_response["responses"]["200"]

    with TestClient(app, raise_server_exceptions=False) as client:
        unknown_responses = (
            (client.get("/api/clips/2147483647"), 404),
            (client.get("/api/clips/2147483647/slots"), 404),
            (client.get("/media/slot-overrides/2147483647"), 404),
            (
                client.patch(
                    "/api/clips/2147483647/slots/1",
                    json={"enabled": True},
                ),
                404,
            ),
            (
                client.delete("/api/clips/2147483647"),
                404,
            ),
            (
                client.get("/api/episodes/2147483647/clips"),
                404,
            ),
            (
                client.post(
                    "/api/episodes/2147483647/clips/preview",
                    json={"shot_ids": [1]},
                ),
                404,
            ),
            (
                client.post(
                    "/api/episodes/2147483647/clips",
                    json={
                        "shot_ids": [1],
                        "reference_asset_ids": [1],
                    },
                ),
                404,
            ),
        )
        for response, status_code in unknown_responses:
            _assert_error(response, status_code)

        invalid_responses = (
            client.post(
                "/api/episodes/2147483647/clips/preview",
                json={"shot_ids": []},
            ),
            client.patch(
                "/api/clips/2147483647/slots/1",
                json={"enabled": 1},
            ),
            client.patch(
                "/api/clips/2147483647/slots/1",
                content=b"enabled=true",
                headers={"content-type": "text/plain"},
            ),
        )
        for response in invalid_responses:
            _assert_error(response, 422)
