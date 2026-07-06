from __future__ import annotations


def _login(web_client) -> None:
    web_client.post(
        "/setup", data={"password": "correcthorsebattery", "confirm": "correcthorsebattery"}
    )


def test_chat_requires_login(web_client) -> None:
    response = web_client.post("/chat", json={"message": "/status"})
    assert response.status_code == 303  # redirected to /setup or /login, not answered


def test_chat_returns_dispatch_result_when_logged_in(web_client, monkeypatch) -> None:
    _login(web_client)

    def fake_dispatch(conn, ai_config, text):
        return f"echo: {text}"

    monkeypatch.setattr("skytracer.web.routes_chat.dispatch", fake_dispatch)

    response = web_client.post("/chat", json={"message": "/status"})
    assert response.status_code == 200
    assert response.json() == {"reply": "echo: /status"}


def test_widget_only_renders_for_logged_in_visitors(web_client) -> None:
    dashboard_anon = web_client.get("/")
    assert 'id="chat-widget"' not in dashboard_anon.text

    _login(web_client)
    dashboard_logged_in = web_client.get("/")
    assert 'id="chat-widget"' in dashboard_logged_in.text
