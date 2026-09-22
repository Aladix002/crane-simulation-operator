import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from pymodbus.client import ModbusTcpClient

HOST = "127.0.0.1"
PORT = 5020
CONFIG_FILE = Path(__file__).parent / "cell.json"
LOG_FILE = Path(__file__).parent / "log.csv"
MOVE_TIMEOUT = 15
POLL_INTERVAL = 0.2

RESET, SET_X, SET_Y, VACUUM, START_P1, START_P2 = 0, 1, 2, 3, 4, 5
AT_X, AT_Y, SOURCE1, SOURCE2 = 15, 16, 17, 18
P1_RUNNING, P2_RUNNING, P1_SENSOR, P2_SENSOR = 19, 20, 21, 22

client = ModbusTcpClient(HOST, port=PORT)
crane = {"x": 0, "y": 0, "part": None, "next_id": 1}
parts_at = {}


def read_input(address):
    result = client.read_holding_registers(address=address, count=1)
    return result.registers[0]


def read_state():
    result = client.read_holding_registers(address=AT_X, count=10)
    return dict(zip(range(AT_X, AT_X + 10), result.registers))


def write_output(address, value):
    client.write_register(address, value)


def move_to(x, y):
    write_output(SET_X, x)
    write_output(SET_Y, y)
    deadline = time.time() + MOVE_TIMEOUT
    while read_input(AT_X) != x or read_input(AT_Y) != y:
        if time.time() > deadline:
            raise RuntimeError(f"Crane did not reach X={x} Y={y}, check the event log")
        time.sleep(0.1)
    crane["x"], crane["y"] = x, y
    if crane["part"] is not None:
        log_position()


def pick_part():
    part = parts_at.pop(crane["x"], None)
    if part is None:
        part = crane["next_id"]
        crane["next_id"] += 1
    crane["part"] = part
    log_position()


def place_part():
    if crane["part"] is not None:
        parts_at[crane["x"]] = crane["part"]
        crane["part"] = None


def start_log():
    with open(LOG_FILE, "w", newline="") as f:
        csv.writer(f).writerow(["product_id", "timestamp", "x", "y", "vacuum"])


def log_position():
    timestamp = datetime.now().isoformat(timespec="seconds")
    with open(LOG_FILE, "a", newline="") as f:
        csv.writer(f).writerow([crane["part"], timestamp, crane["x"], crane["y"], 1])


def run_action(action, positions):
    if "pos" in action:
        action = positions[action["pos"]]
    if "setX" in action:
        move_to(action["setX"], action["setY"])
    if "vacuum" in action:
        write_output(VACUUM, action["vacuum"])
        if action["vacuum"] == 1:
            pick_part()
        else:
            place_part()
    if "process" in action:
        write_output(START_P1 + action["process"] - 1, 1)


def run_sequence(config, name):
    for action in config["sequences"][name]:
        print(action)
        run_action(action, config["positions"])


def choose_sequence(state):
    if state[P1_SENSOR] == 1 and state[P1_RUNNING] == 0:
        return "p1_to_sink"
    if state[SOURCE1] == 1 and state[P1_SENSOR] == 0:
        return "s1_to_p1"
    return None


def run_auto(config):
    print("Auto mode, waiting for parts (Ctrl+C to stop)")
    while True:
        name = choose_sequence(read_state())
        if name:
            print(f"-> {name}")
            run_sequence(config, name)
        else:
            time.sleep(POLL_INTERVAL)


def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)


def main():
    config = load_config()
    start_log()
    if not client.connect():
        print(f"Could not connect to the simulation on {HOST}:{PORT}")
        return
    try:
        if len(sys.argv) > 1:
            run_sequence(config, sys.argv[1])
        else:
            run_auto(config)
    except KeyboardInterrupt:
        print("Stopped")
    finally:
        client.close()


if __name__ == "__main__":
    main()
