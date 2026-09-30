"""Protocol round-trip test: bridge (PC) <-> emulated phone (client).

Validates the CSV wire format used by BridgeClient.java and PhoneLink:
state line S,... in, command line C,... out, RTT echo included.
"""
import socket
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bridge"))

from ets2ai import sim                                  # noqa: E402
from ets2_bridge import PhoneLink, load_policy, policy_cmd  # noqa: E402


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_phone_link_roundtrip():
    port = _free_port()
    link = PhoneLink(port)
    link.start()
    time.sleep(0.2)

    road = sim.Road.random(777)
    truck = sim.Truck(road, s=5.0, offset=0.5, speed=16.0)

    phone = socket.create_connection(("127.0.0.1", port), timeout=5)
    phone.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    # wait for the server thread to register the connection
    for _ in range(50):
        if link.connected:
            break
        time.sleep(0.05)
    assert link.connected

    link.send_state(road, truck, job_left_km=5.0)
    raw = phone.makefile("rb").readline().decode().strip()
    parts = raw.split(",")
    assert parts[0] == "S" and len(parts) == 14, raw
    # normalization sanity: speed and fuel are raw physical values
    assert abs(float(parts[1]) - truck.speed) < 1e-3
    assert 0.0 <= float(parts[10]) <= 1.0 and 0.0 <= float(parts[11]) <= 1.0

    # phone replies like BridgeClient.java would
    t_echo = parts[13]
    phone.sendall(f"C,0.1,0.8,0.0,{t_echo}\n".encode())

    for _ in range(50):
        if link.latest_cmd is not None:
            break
        time.sleep(0.05)
    assert link.latest_cmd is not None
    steer, throttle, brake, echoed = link.latest_cmd
    assert abs(steer - 0.1) < 1e-6 and abs(throttle - 0.8) < 1e-6
    assert abs(brake) < 1e-6
    assert echoed == float(t_echo)
    assert link.rtt_ms >= 0.0

    phone.close()


def test_local_policy_drives_for_bridge():
    """The bridge's local fallback (same weights) keeps the truck in lane."""
    layers = load_policy()
    road = sim.Road.random(90211)
    truck = sim.Truck(road, s=5.0, offset=1.5, speed=18.0)
    in_lane = 0
    steps = 1500
    for _ in range(steps):
        cmd = policy_cmd(layers, road, truck, max(0.0, (road.length - truck.s) / 1000.0))
        truck.step(road, cmd[0], cmd[1], cmd[2])
        if abs(truck.offset) < sim.LANE_HALF:
            in_lane += 1
        if truck.s >= road.length - 10 or abs(truck.offset) > sim.ROAD_HALF:
            break
    assert in_lane / steps > 0.9
