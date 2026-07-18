from test_frontend_main_alignment import _client


def test_openapi_characterization_preserves_public_route_set():
    schema = _client().openapi()

    assert schema["info"]["title"] == "AGI Assistant"
    assert schema["info"]["version"] == "1.0"
    assert set(schema["paths"]) == {
        "/health",
        "/api/chat",
        "/api/chat/stream",
        "/api/chat/cancel",
        "/api/docs/delete",
        "/api/upload",
        "/api/documents",
        "/api/documents/{document_id}",
        "/api/documents/{document_id}/ingest",
        "/api/tools",
        "/api/tools/mcp",
        "/api/status",
        "/api/memory",
        "/api/snapshots",
    }


def test_openapi_chat_contract_requires_message_and_preserves_stream_route():
    schema = _client().openapi()
    chat_schema = schema["components"]["schemas"]["ChatRequest"]

    assert chat_schema["required"] == ["message"]
    assert chat_schema["properties"]["message"]["minLength"] == 1
    assert chat_schema["properties"]["use_rag"]["default"] is False
    assert chat_schema["properties"]["explicit"]["default"] is False
    assert "post" in schema["paths"]["/api/chat/stream"]
