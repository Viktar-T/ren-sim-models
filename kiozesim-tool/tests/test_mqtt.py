"""Spec 0012: the MQTT sink, against a fake paho client (no broker needed)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import yaml
from paho.mqtt import client as mqtt
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.reasoncodes import ReasonCode
from pydantic import ValidationError

from kiozesim_tool import cli, config
from kiozesim_tool.mqtt import MAX_QUEUED, MqttSettings, MqttSink
from kiozesim_tool.sink import SINKS, Sample, StdoutSink

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
T0 = pd.Timestamp("2026-10-08 10:00", tz="UTC")
OK = ReasonCode(PacketTypes.CONNACK, "Success")
BAD_LOGIN = ReasonCode(PacketTypes.CONNACK, "Bad user name or password")
LOST = ReasonCode(PacketTypes.DISCONNECT, "Unspecified error")
BYE = ReasonCode(PacketTypes.DISCONNECT, "Normal disconnection")


class Info:
    def __init__(self, rc: int = mqtt.MQTT_ERR_SUCCESS, published: bool = True) -> None:
        self.rc = rc
        self.published = published

    def is_published(self) -> bool:
        return self.published


class FakeClient:
    """Records calls. `mode`: accept, refuse, unreachable, silent."""

    def __init__(self, client_id: str, mode: str = "accept") -> None:
        self.client_id = client_id
        self.mode = mode
        self.calls: list[str] = []
        self.login: tuple[str, str | None] | None = None
        self.published: list[tuple[str, str, int, bool]] = []
        self.connect_timeout = 0.0
        self.online = False
        self.on_connect: Any = None
        self.on_disconnect: Any = None

    def username_pw_set(self, username: str, password: str | None) -> None:
        self.login = (username, password)

    def reconnect_delay_set(self, min_delay: int, max_delay: int) -> None:
        self.calls.append(f"backoff {min_delay}-{max_delay}")

    def connect(self, host: str, port: int) -> None:
        self.calls.append(f"connect {host}:{port}")
        if self.mode == "unreachable":
            raise ConnectionRefusedError("Connection refused")

    def loop_start(self) -> None:
        self.calls.append("loop_start")
        if self.mode == "accept":
            self.go_online()
        elif self.mode == "refuse":
            self.on_connect(self, None, None, BAD_LOGIN, None)

    def loop_stop(self) -> None:
        self.calls.append("loop_stop")

    def disconnect(self) -> None:
        self.calls.append("disconnect")
        self.online = False
        self.on_disconnect(self, None, None, BYE, None)

    def publish(self, topic: str, payload: str, qos: int, retain: bool) -> Info:
        if not self.online:
            return Info(mqtt.MQTT_ERR_NO_CONN, published=False)
        self.published.append((topic, payload, qos, retain))
        return Info()

    # test helpers: what paho's thread would do
    def go_online(self) -> None:
        self.online = True
        self.on_connect(self, None, None, OK, None)

    def drop(self) -> None:
        self.online = False
        self.on_disconnect(self, None, None, LOST, None)


def make(mode: str = "accept", **settings: Any) -> tuple[MqttSink, list[FakeClient]]:
    clients: list[FakeClient] = []

    def factory(client_id: str) -> FakeClient:
        clients.append(FakeClient(client_id, mode))
        return clients[-1]

    s = MqttSettings.model_validate({"host": "broker", "topic": "kioze/plants", **settings})
    return MqttSink(s, client_factory=factory), clients


def sample(i: int = 0) -> Sample:
    return Sample(T0 + pd.Timedelta(hours=i), pd.Timedelta("1h"), {"roof": 1.5 + i})


# --- registration and settings ---


@pytest.mark.spec("MQTT-001")
def test_registered_as_mqtt() -> None:
    assert SINKS["mqtt"] is MqttSink
    sink = config.build_sinks([{"type": "mqtt", "host": "h", "topic": "t"}])[0]
    assert isinstance(sink, MqttSink)


@pytest.mark.spec("MQTT-002")
def test_defaults_and_unknown_key() -> None:
    s = MqttSettings(host="h", topic="t")
    assert (s.port, s.qos, s.retain, s.client_id, s.connect_timeout_s) == (1883, 1, False, "", 10)
    with pytest.raises(ValidationError, match="tls"):
        MqttSettings.model_validate({"host": "h", "topic": "t", "tls": True})


@pytest.mark.spec("MQTT-003")
@pytest.mark.parametrize(
    "login",
    [{"username": "u"}, {"password": "p"}, {"username": "u", "password": "p", "password_env": "X"}],
)
def test_login_pairing(login: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        MqttSettings.model_validate({"host": "h", "topic": "t", **login})
    MqttSettings(host="h", topic="t", username="u", password="p")


@pytest.mark.spec("MQTT-005")
def test_password_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KIOZE_PW", "secret")
    s = MqttSettings(host="h", topic="t", username="u", password_env="KIOZE_PW")
    assert s.password == "secret"
    monkeypatch.delenv("KIOZE_PW")
    with pytest.raises(ValidationError, match="KIOZE_PW"):
        MqttSettings(host="h", topic="t", username="u", password_env="KIOZE_PW")


@pytest.mark.spec("MQTT-004")
@pytest.mark.parametrize(
    "bad",
    [
        {"topic": "t"},
        {"host": "h"},
        {"host": "h", "topic": ""},
        {"host": "h", "topic": "kioze/+"},
        {"host": "h", "topic": "kioze/#"},
        {"host": "h", "topic": "t", "port": 0},
        {"host": "h", "topic": "t", "port": 70000},
        {"host": "h", "topic": "t", "qos": 3},
    ],
)
def test_invalid_settings(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        MqttSettings.model_validate(bad)


@pytest.mark.spec("MQTT-004")
def test_invalid_settings_fail_before_sending(tmp_path: Path, capsys: Any) -> None:
    cfg = yaml.safe_load((EXAMPLES / "mqtt.yaml").read_text())
    cfg["weather"]["path"] = str(EXAMPLES / "day_weather.csv")
    cfg["sinks"] = [{"type": "mqtt", "host": "h", "topic": "a/#"}, {"type": "stdout"}]
    path = tmp_path / "c.yaml"
    path.write_text(yaml.safe_dump(cfg))
    assert cli.main(["sink", "1h", "--config", str(path)]) == 2
    out = capsys.readouterr()
    assert out.out == "" and "wildcard" in out.err


# --- connection ---


@pytest.mark.spec("MQTT-010")
def test_open_waits_for_broker() -> None:
    sink, clients = make(username="u", password="p", client_id="sim-1", connect_timeout_s=3)
    sink.open()
    c = clients[0]
    assert c.client_id == "sim-1" and c.login == ("u", "p") and c.connect_timeout == 3
    assert c.calls[-2:] == ["connect broker:1883", "loop_start"]
    assert sink._connected


@pytest.mark.spec("MQTT-011")
@pytest.mark.parametrize(
    ("mode", "message"),
    [("unreachable", "cannot reach"), ("refuse", "refused"), ("silent", "did not answer")],
)
def test_open_fails_clearly(mode: str, message: str) -> None:
    sink, clients = make(mode, port=1884, connect_timeout_s=0.05)
    with pytest.raises(ConnectionError) as e:
        sink.open()
    assert "broker:1884" in str(e.value) and message in str(e.value)
    if mode != "unreachable":  # background thread was started, so it must be stopped again
        assert clients[0].calls[-1] == "loop_stop"


@pytest.mark.spec("MQTT-011")
def test_cli_exits_nonzero_when_broker_unreachable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    monkeypatch.setattr(
        "kiozesim_tool.mqtt.paho_client", lambda cid: FakeClient(cid, "unreachable")
    )
    cfg = yaml.safe_load((EXAMPLES / "mqtt.yaml").read_text())
    cfg.update(speed=0, start="2026-06-01T00:00", end="2026-06-01T03:00")
    cfg["weather"]["path"] = str(EXAMPLES / "day_weather.csv")
    path = tmp_path / "c.yaml"
    path.write_text(yaml.safe_dump(cfg))
    assert cli.main(["sink", "1h", "--config", str(path)]) == 2
    out = capsys.readouterr()
    assert out.out == ""  # the stdout sink got nothing either
    assert "cannot reach MQTT broker at localhost:1883" in out.err


@pytest.mark.spec("MQTT-012")
def test_close_flushes_then_disconnects() -> None:
    sink, clients = make()
    with sink:
        sink.send(sample())
    assert clients[0].calls[-2:] == ["disconnect", "loop_stop"]
    sink.close()  # second close is harmless
    MqttSink(MqttSettings(host="h", topic="t")).close()  # never opened


@pytest.mark.spec("MQTT-012")
def test_close_waits_for_in_flight(capsys: Any) -> None:
    sink, clients = make(connect_timeout_s=0.1)
    sink.open()
    pending = Info(published=False)
    clients[0].publish = lambda *a, **k: pending  # type: ignore[method-assign]
    sink.send(sample())
    sink.close()
    assert "1 readings were not delivered" in capsys.readouterr().err
    pending.published = True
    sink2, c2 = make()
    sink2.open()
    sink2.send(sample())
    sink2.close()
    assert capsys.readouterr().err == ""


# --- sending ---


@pytest.mark.spec("MQTT-020")
@pytest.mark.spec("MQTT-021")
@pytest.mark.spec("MQTT-023")
def test_payload_topic_qos_retain() -> None:
    sink, clients = make(qos=2, retain=True)
    with sink:
        sink.send(sample(0))
        sink.send(sample(1))
    topic, payload, qos, retain = clients[0].published[0]
    assert (topic, qos, retain) == ("kioze/plants", 2, True)
    assert not payload.endswith("\n")
    assert json.loads(payload) == {
        "time": "2026-10-08T10:00:00Z",
        "step_s": 3600,
        "power_kw": {"roof": 1.5},
    }
    assert {p[0] for p in clients[0].published} == {"kioze/plants"}


@pytest.mark.spec("MQTT-020")
def test_payload_matches_stdout_sink() -> None:
    import io

    buf = io.StringIO()
    StdoutSink(buf).send(sample())
    sink, clients = make()
    with sink:
        sink.send(sample())
    assert clients[0].published[0][1] + "\n" == buf.getvalue()


@pytest.mark.spec("MQTT-022")
def test_send_does_not_wait_for_confirmation() -> None:
    sink, clients = make()
    sink.open()
    never = Info(published=False)
    clients[0].publish = lambda *a, **k: never  # type: ignore[method-assign]
    sink.send(sample())  # returns although the broker never confirms
    assert sink._in_flight == [never]


# --- lost connection ---


@pytest.mark.spec("MQTT-030")
def test_reconnect_backoff_configured() -> None:
    sink, clients = make()
    sink.open()
    assert "backoff 1-60" in clients[0].calls


@pytest.mark.spec("MQTT-031")
def test_readings_kept_and_sent_in_order_after_reconnect() -> None:
    sink, clients = make()
    sink.open()
    c = clients[0]
    sink.send(sample(0))
    c.drop()
    sink.send(sample(1))
    sink.send(sample(2))
    assert len(c.published) == 1
    c.go_online()
    sink.send(sample(3))
    times = [json.loads(p[1])["time"][11:13] for p in c.published]
    assert times == ["10", "11", "12", "13"]


@pytest.mark.spec("MQTT-031")
def test_publish_failing_mid_drop_keeps_reading() -> None:
    sink, clients = make()
    sink.open()
    c = clients[0]
    c.online = False  # line gone, paho has not noticed yet
    sink.send(sample(0))
    assert sink._queue and not c.published
    c.go_online()
    assert len(c.published) == 1 and not sink._queue


@pytest.mark.spec("MQTT-032")
def test_too_many_waiting_stops_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("kiozesim_tool.mqtt.MAX_QUEUED", 3)
    sink, clients = make()
    sink.open()
    clients[0].drop()
    for i in range(3):
        sink.send(sample(i))
    with pytest.raises(ConnectionError, match="3 readings waiting"):
        sink.send(sample(3))
    assert MAX_QUEUED == 10_000


@pytest.mark.spec("MQTT-033")
def test_drop_and_reconnect_reported_once(capsys: Any) -> None:
    sink, clients = make()
    sink.open()
    c = clients[0]
    assert capsys.readouterr().err == ""
    c.drop()
    c.drop()  # paho may report again while retrying; only the first counts
    sink.send(sample())
    c.go_online()
    sink.close()  # clean disconnect: not reported
    err = capsys.readouterr().err.splitlines()
    assert err == [
        "mqtt: connection to broker:1883 lost, reconnecting",
        "mqtt: reconnected to broker:1883, sending 1 waiting readings",
    ]


# --- testability and packaging ---


@pytest.mark.spec("MQTT-040")
def test_client_is_injectable() -> None:
    sink, clients = make()
    sink.open()
    assert len(clients) == 1 and isinstance(clients[0], FakeClient)


@pytest.mark.spec("MQTT-041")
def test_paho_is_a_dependency() -> None:
    import tomllib

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    deps = tomllib.loads(pyproject.read_text())["project"]["dependencies"]
    assert any(d.replace(" ", "").startswith("paho-mqtt>=2") for d in deps)
    from kiozesim_tool.mqtt import paho_client

    assert isinstance(paho_client("x"), mqtt.Client)
