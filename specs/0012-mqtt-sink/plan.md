# 0012 plan

## Modules (`kiozesim-tool/src/kiozesim_tool/`)
- `mqtt.py`:
  - `MqttSettings`: frozen pydantic model, `extra="forbid"` (MQTT-002..005). Validates topic (non-empty,
    no `+`/`#`), port range, qos, login pairing; resolves `password_env` from `os.environ`.
  - `MqttSink(settings, client_factory=paho_client)`. `client_factory(client_id)` returns a
    paho-like client (MQTT-040); the default builds a paho 2 `Client` with callback API version 2.
  - `open()`: `connect_timeout` on the client, login, `reconnect_delay_set(1, 60)` (MQTT-030),
    `connect()` (socket errors -> `ConnectionError` naming host:port), `loop_start()`, then wait on a
    `threading.Event` set by `on_connect`. Refused / timed out -> `ConnectionError` (MQTT-010/011).
  - `send()`: under a lock, append the payload to a `deque`; if connected, drain the deque with
    `publish(topic, payload, qos, retain)` (MQTT-020..023). `on_connect` after a drop drains it too,
    so queued readings go out first and in order (MQTT-031). More than 10 000 waiting ->
    `ConnectionError` (MQTT-032). Drop/reconnect notes go to stderr once each (MQTT-033).
  - `close()`: poll `is_published()` of in-flight messages until done or `connect_timeout_s`, warn
    about readings never delivered, `disconnect()`, `loop_stop()`. No-op if never opened (MQTT-012).
  - Registers itself: `SINKS["mqtt"] = MqttSink`. `kiozesim_tool/__init__.py` imports `mqtt` so the
    registry is complete whenever the package is imported (no circular import with `sink.py`).
- `sink.py`: `Sample.to_json() -> str`, shared by the stdout and mqtt sinks (same payload, MQTT-020).
- `cli.py`: errors raised while sinks open or send (`OSError`, which includes `ConnectionError`)
  print a clear message and return exit code 2 instead of a traceback (MQTT-011, MQTT-032).

## Packaging
- `paho-mqtt>=2` in `kiozesim-tool` dependencies (MQTT-041).
- `kiozesim-tool/examples/mqtt.yaml`: the sink example pointing at `localhost:1883`.

## Tests (`kiozesim-tool/tests/test_mqtt.py`)
A `FakeClient` records calls and fires `on_connect` / `on_disconnect` on demand; modes for accept,
refuse, unreachable and silent (timeout). No real broker in CI.

## Risks
- Callbacks run in paho's thread; the lock keeps the queue and ordering consistent with `send`.
- QoS 0 messages in flight when the line drops can be lost; that is what QoS 0 means. Default is 1.
