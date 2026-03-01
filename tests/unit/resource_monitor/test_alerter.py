import time
import pytest
from unittest.mock import MagicMock, patch

from resource_monitor.alerter import Alerter
from resource_monitor.detector import AnomalyResult


def _anomaly(container="producer", metric="cpu_pct", z=3.5, value=80.0, ema=50.0, hour=10):
    return AnomalyResult(
        container=container,
        metric=metric,
        current_value=value,
        ema=ema,
        z_score=z,
        hour=hour,
    )


@pytest.fixture
def mock_httpx(mocker):
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_cm
    mock_cm.__exit__.return_value = False
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_cm.post.return_value = mock_resp
    mocker.patch("resource_monitor.alerter.httpx.Client", return_value=mock_cm)
    return mock_cm


def test_send_posts_to_webhook(mock_httpx):
    alerter = Alerter("https://discord.example/webhook", cooldown_seconds=3600)
    alerter.send(_anomaly())
    mock_httpx.post.assert_called_once()
    call_kwargs = mock_httpx.post.call_args
    assert "embeds" in call_kwargs.kwargs["json"]


def test_no_send_when_webhook_empty(mocker):
    mock_post = mocker.patch("resource_monitor.alerter.httpx.Client")
    alerter = Alerter("", cooldown_seconds=3600)
    alerter.send(_anomaly())
    mock_post.assert_not_called()


def test_cooldown_suppresses_second_alert(mock_httpx):
    alerter = Alerter("https://discord.example/webhook", cooldown_seconds=3600)
    alerter.send(_anomaly())
    alerter.send(_anomaly())  # 두 번째는 억제
    assert mock_httpx.post.call_count == 1


def test_different_metric_not_suppressed(mock_httpx):
    alerter = Alerter("https://discord.example/webhook", cooldown_seconds=3600)
    alerter.send(_anomaly(metric="cpu_pct"))
    alerter.send(_anomaly(metric="mem_pct"))
    assert mock_httpx.post.call_count == 2


def test_different_container_not_suppressed(mock_httpx):
    alerter = Alerter("https://discord.example/webhook", cooldown_seconds=3600)
    alerter.send(_anomaly(container="producer"))
    alerter.send(_anomaly(container="clickhouse"))
    assert mock_httpx.post.call_count == 2


def test_cooldown_expires(mock_httpx, mocker):
    alerter = Alerter("https://discord.example/webhook", cooldown_seconds=1)
    alerter.send(_anomaly())
    # monotonic을 냉각 시간 이후로 이동
    mocker.patch("resource_monitor.alerter.time.monotonic", return_value=time.monotonic() + 2)
    alerter.send(_anomaly())
    assert mock_httpx.post.call_count == 2


def test_embed_fields_contain_z_score(mock_httpx):
    alerter = Alerter("https://discord.example/webhook", cooldown_seconds=3600)
    alerter.send(_anomaly(z=4.2, value=90.0, ema=50.0, hour=14))
    payload = mock_httpx.post.call_args.kwargs["json"]
    embed = payload["embeds"][0]
    field_values = {f["name"]: f["value"] for f in embed["fields"]}
    assert "4.20" in field_values["z-score"]
    assert "14시" in list(field_values.keys())[4]  # 시간대 평균 필드


def test_embed_direction_급증(mock_httpx):
    alerter = Alerter("https://discord.example/webhook", cooldown_seconds=3600)
    alerter.send(_anomaly(z=3.0))
    payload = mock_httpx.post.call_args.kwargs["json"]
    embed = payload["embeds"][0]
    fields = {f["name"]: f["value"] for f in embed["fields"]}
    assert fields["방향"] == "급증"


def test_embed_direction_급감(mock_httpx):
    alerter = Alerter("https://discord.example/webhook", cooldown_seconds=3600)
    alerter.send(_anomaly(z=-3.0))
    payload = mock_httpx.post.call_args.kwargs["json"]
    embed = payload["embeds"][0]
    fields = {f["name"]: f["value"] for f in embed["fields"]}
    assert fields["방향"] == "급감"


def test_send_handles_httpx_error(mock_httpx):
    mock_httpx.post.side_effect = Exception("connection refused")
    alerter = Alerter("https://discord.example/webhook", cooldown_seconds=3600)
    # 예외가 전파되지 않아야 함
    alerter.send(_anomaly())
