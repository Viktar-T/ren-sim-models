"""MQTT sink: publishes each reading to a topic on an MQTT broker (spec 0012)."""

from __future__ import annotations

import os
import sys
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from typing import Any, Literal, Self

from paho.mqtt import client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from kiozesim_tool.sink import SINKS, Sample, Sink

MAX_QUEUED = 10_000  # MQTT-032


class MqttSettings(BaseModel):
    """The `mqtt` entry under `sinks:` in the config file (MQTT-002..005)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    host: str = Field(min_length=1)
    port: int = Field(default=1883, ge=1, le=65535)
    topic: str = Field(min_length=1)
    username: str | None = None
    password: str | None = None
    password_env: str | None = None
    client_id: str = ""  # empty: a unique one is picked automatically
    qos: Literal[0, 1, 2] = 1
    retain: bool = False
    connect_timeout_s: float = Field(default=10.0, gt=0)

    @field_validator("topic")
    @classmethod
    def _no_wildcards(cls, v: str) -> str:
        if "+" in v or "#" in v:
            raise ValueError("topic must not contain the wildcards '+' or '#'")
        return v

    @model_validator(mode="after")
    def _login(self) -> MqttSettings:
        if self.password is not None and self.password_env is not None:
            raise ValueError("give either password or password_env, not both")
        if self.password_env is not None:
            if self.password_env not in os.environ:
                raise ValueError(f"environment variable {self.password_env!r} is not set")
            object.__setattr__(self, "password", os.environ[self.password_env])
        if (self.username is None) != (self.password is None):
            raise ValueError("username and password must be both present or both absent")
        return self


def paho_client(client_id: str) -> Any:
    return mqtt.Client(
        callback_api_version=CallbackAPIVersion.VERSION2,
        client_id=client_id,
    )


class MqttSink(Sink):
    """One JSON message per sample on one topic; queues readings while disconnected (MQTT-001)."""

    def __init__(
        self,
        settings: MqttSettings,
        client_factory: Callable[[str], Any] | None = None,  # MQTT-040; None: paho
    ) -> None:
        self.settings = settings
        self._factory = client_factory
        self._client: Any = None
        self._lock = threading.Lock()
        self._connected = False
        self._ever_connected = False
        self._answered = threading.Event()
        self._refused: str | None = None
        self._queue: deque[str] = deque()
        self._in_flight: list[Any] = []

    @classmethod
    def from_settings(cls, settings: Mapping[str, Any]) -> Self:
        return cls(MqttSettings.model_validate(dict(settings)))

    @property
    def _where(self) -> str:
        return f"{self.settings.host}:{self.settings.port}"

    def open(self) -> None:
        s = self.settings
        client = (self._factory or paho_client)(s.client_id)
        client.connect_timeout = s.connect_timeout_s
        if s.username is not None:
            client.username_pw_set(s.username, s.password)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.reconnect_delay_set(min_delay=1, max_delay=60)  # MQTT-030
        try:
            client.connect(s.host, s.port)
        except OSError as e:
            raise ConnectionError(f"cannot reach MQTT broker at {self._where}: {e}") from e
        self._client = client
        client.loop_start()
        error = None
        if not self._answered.wait(s.connect_timeout_s):  # MQTT-010
            error = f"MQTT broker at {self._where} did not answer within {s.connect_timeout_s:g} s"
        elif self._refused is not None:
            error = f"MQTT broker at {self._where} refused: {self._refused}"
        if error is not None:  # MQTT-011; the context manager will not call close() for us
            self.close()
            raise ConnectionError(error)

    def _on_connect(self, client: Any, userdata: Any, flags: Any, reason: Any, props: Any) -> None:
        if reason.is_failure:
            if not self._ever_connected:
                self._refused = str(reason)
                self._answered.set()
            return
        with self._lock:
            if self._ever_connected:  # MQTT-033
                n = len(self._queue)
                msg = f"mqtt: reconnected to {self._where}, sending {n} waiting readings"
                print(msg, file=sys.stderr)
            self._connected = True
            self._ever_connected = True
            self._drain()  # MQTT-031: waiting readings first, in order
        self._answered.set()

    def _on_disconnect(
        self, client: Any, userdata: Any, flags: Any, reason: Any, props: Any
    ) -> None:
        with self._lock:
            was_connected = self._connected
            self._connected = False
        if was_connected and reason.is_failure:  # MQTT-033; a clean close() is not reported
            print(f"mqtt: connection to {self._where} lost, reconnecting", file=sys.stderr)

    def _drain(self) -> None:
        """Publish waiting readings in order. Caller holds the lock."""
        s = self.settings
        while self._queue and self._connected:
            info = self._client.publish(s.topic, self._queue[0], qos=s.qos, retain=s.retain)
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                break  # line dropped in between; keep it for the reconnect
            self._queue.popleft()
            self._in_flight.append(info)
        self._in_flight = [i for i in self._in_flight if not i.is_published()]

    def send(self, sample: Sample) -> None:
        """Hand the reading to the background thread; never waits (MQTT-020..023, SINK-003)."""
        if self._client is None:
            raise RuntimeError("MqttSink.send called before open()")
        with self._lock:
            if len(self._queue) >= MAX_QUEUED:  # MQTT-032
                raise ConnectionError(
                    f"MQTT broker at {self._where} unreachable for too long: "
                    f"{len(self._queue)} readings waiting"
                )
            self._queue.append(sample.to_json())
            self._drain()

    def close(self) -> None:
        client = self._client
        if client is None:  # MQTT-012: never opened, or open() failed before connecting
            return
        deadline = time.monotonic() + self.settings.connect_timeout_s
        while time.monotonic() < deadline:
            with self._lock:
                self._in_flight = [i for i in self._in_flight if not i.is_published()]
                if not self._in_flight:
                    break
            time.sleep(0.05)
        lost = len(self._queue) + len(self._in_flight)
        if lost:
            print(f"mqtt: {lost} readings were not delivered to {self._where}", file=sys.stderr)
        with self._lock:
            self._connected = False
        client.disconnect()
        client.loop_stop()
        self._client = None


SINKS["mqtt"] = MqttSink  # SINK-004, MQTT-001
