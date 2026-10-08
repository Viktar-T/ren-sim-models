---
id: 0012
title: MQTT sink
prefix: MQTT
status: implemented
---

# 0012 MQTT sink

## Problem
`kiozesim-tool sink` (spec 0011) can pretend to be a live plant, but today it only prints readings to
the terminal. Dashboards, controllers and energy-management systems usually listen to an **MQTT
broker**, the way they would listen to a real plant's meter. This spec adds an `mqtt` sink so the
simulated readings arrive there, one message per reading, exactly as if a real meter sent them.

It only adds a new sink; the command, the player and the `Sink` interface from spec 0011 stay as they
are (SINK-004: a sink is one class plus one registry line).

## Scope
In:
- An `MqttSink` class in `kiozesim_tool.mqtt`, registered as `mqtt` in `SINKS`.
- Its settings in the config file's `sinks:` list (broker address, port, topic, optional login).
- What a message looks like and which topic it goes to.
- What happens when the broker cannot be reached at start, or the connection drops mid-run.

Out:
- Receiving messages (subscribing). The tool only sends.
- Encrypted connections (TLS, `mqtts://`, port 8883) and client certificates: a later spec.
- One topic per plant: a later spec if needed.
- MQTT over WebSockets.
- Running or bundling a broker. The user brings their own (e.g. Mosquitto).
- Any change to the player, the weather source or the `Sample` fields.

## Domain notes
- *MQTT*: a lightweight "post office" protocol for machines. A program **publishes** a message to a
  named **topic** (a path such as `kioze/plants/roof`); every program **subscribed** to that topic
  gets a copy. Nobody talks to anybody directly; everyone talks to the post office.
- *Broker*: the post office itself, a server program (Mosquitto, EMQX, HiveMQ, ...) reached by a host
  name or IP address and a **port** (a "door number" on that machine; MQTT's usual door is `1883`).
- *Client*: any program connected to the broker. Our sink is one client. Each client has a
  **client ID**, a name the broker uses to tell clients apart. Two clients with the same ID kick each
  other off, so IDs should be unique.
- *Username / password*: many brokers only let known clients in. Either both are given or neither.
- *QoS ("quality of service")*: how hard the post office tries to deliver.
  `0` = "drop it in the letterbox", may get lost if the line is bad.
  `1` = "registered letter", the broker confirms receipt; if no confirmation, it is sent again, so a
  receiver may now and then see the same reading twice.
  `2` = "exactly once", slowest, rarely needed.
  Duplicates are harmless here because every reading carries its own timestamp (spec 0011, delivery
  delay): a receiver that stores by `time` just overwrites the same value.
- *Retain*: a flag asking the broker to keep the *last* message on a topic and hand it to anyone who
  subscribes later, like a note pinned to the door. Useful so a dashboard opened mid-run immediately
  shows the latest reading.
- *Background network thread*: the MQTT library keeps the connection alive in its own thread. That is
  why `send` can hand a message over and return straight away, without waiting (SINK-003).
- *paho-mqtt*: the standard Python MQTT client library, used to implement this sink.

```
Player ─► Sample ─► MqttSink.send ─► paho client (background thread) ─► broker ─► subscribers
                                                                         (topic: kioze/plants)
```

## Requirements

### Registration and settings
- **MQTT-001** `kiozesim_tool.mqtt` MUST define `MqttSink`, a `Sink` (SINK-002), registered in `SINKS`
  under the name `mqtt`.
- **MQTT-002** `MqttSink.from_settings` MUST accept these config keys and reject any other:
  `host` (required), `port` (default `1883`), `topic` (required), `username`, `password`,
  `password_env`, `client_id` (default empty: a unique one is picked automatically), `qos`
  (default `1`), `retain` (default `false`), `connect_timeout_s` (default `10`).
- **MQTT-003** `username` and a password MUST be either both given or both absent; the password is
  given either as `password` or as `password_env` (the name of an environment variable holding it),
  never both. Otherwise the config MUST be rejected.
- **MQTT-005** With `password_env`, the password MUST be read from that environment variable when the
  config is loaded; if the variable is not set, the config MUST be rejected naming the variable.
- **MQTT-004** Invalid settings (missing `host`/`topic`, port outside `1..65535`, `qos` not 0/1/2,
  empty topic, a topic containing the wildcards `+` or `#`) MUST fail at config time, before
  anything is sent (SINK-023).

### Connection
- **MQTT-010** `open()` MUST connect to the broker and wait until the broker accepts the connection
  (or refuses it) before returning, up to `connect_timeout_s`.
- **MQTT-011** If the broker is unreachable, refuses the login, or does not answer within the timeout,
  `open()` MUST raise an error with a clear message naming host and port, so the command exits
  non-zero before any reading is sent (SINK-023).
- **MQTT-012** `close()` MUST wait (up to `connect_timeout_s`) until readings already handed over have left
  for the broker, then disconnect cleanly and stop the background thread. `close()` MUST be safe to
  call when `open()` failed or was never called.

### Sending
- **MQTT-020** `send(sample)` MUST publish one message per sample whose payload is the same JSON
  object the `stdout` sink prints (SINK-030), UTF-8 encoded, without a trailing newline.
- **MQTT-021** All samples MUST go to the one configured `topic`.
- **MQTT-022** `send` MUST NOT wait for the broker's confirmation; it hands the message to the
  background thread and returns (SINK-003).
- **MQTT-023** Each message MUST be published with the configured `qos` and `retain` flag.

### Lost connection
- **MQTT-030** If the connection drops during playback, the sink MUST try to reconnect on its own in
  the background, waiting longer between attempts (1 s, 2 s, 4 s ... up to 60 s).
- **MQTT-031** While disconnected, `send` MUST keep the readings in memory, and after reconnecting
  MUST deliver them in their original order, before any newer reading. No reading is dropped
  (SINK-015).
- **MQTT-032** If more than 10 000 readings are waiting, `send` MUST raise an error so the run stops
  (exit code non-zero, clear message) instead of using ever more memory.
- **MQTT-033** Each drop and each successful reconnect MUST be reported once on stderr.

### Testability and packaging
- **MQTT-040** The MQTT client MUST be injectable (a factory passed to `MqttSink`), so tests run
  without a real broker.
- **MQTT-041** `paho-mqtt` (version 2 or later) MUST be a normal (always installed) dependency of
  `kiozesim-tool`.

## Acceptance
- Unit tests with a fake client cover settings validation, connect success/failure/timeout, payload
  and topic, QoS/retain, close-flushes, and disconnect/reconnect behaviour.
- `kiozesim-tool/examples/` gains an `mqtt.yaml`; with a local Mosquitto running,
  `uv run kiozesim-tool sink 15min --config kiozesim-tool/examples/mqtt.yaml` and
  `mosquitto_sub -t 'kioze/#' -v` show one JSON message per reading. (Manual check, not in CI.)
- `scripts/spec_check.py`, `pytest`, `ruff`, `mypy` are green.

Example config entry:

```yaml
sinks:
  - type: mqtt
    host: localhost
    port: 1883
    topic: kioze/plants
    # username: sim
    # password: secret
```

## Open questions
None. Resolved 2026-10-08: (1) one topic; (2) connect timeout 10 s, `connect_timeout_s`;
(3) `qos: 1`, `retain: false`, automatic `client_id`; (4) keep readings while disconnected and send
them after reconnecting, stop the run above 10 000 waiting; (5) TLS in a later spec; (6) `paho-mqtt`
always installed; (7) `password_env` as an alternative to `password`.

## Changelog
- 2026-10-08 created (draft)
- 2026-10-08 open questions resolved (MQTT-005, MQTT-032, MQTT-033 added); approved
- 2026-10-08 implemented (manual check against a real broker still to do)
