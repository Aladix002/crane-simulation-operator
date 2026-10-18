import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from pymodbus.client import ModbusTcpClient

HOST = "127.0.0.1"
PORT = 502 if sys.platform.startswith("win") else 5020
CONFIG_FILE = Path(__file__).parent / "crane.json"
LOG_FILE = Path(__file__).parent / "log.csv"
SAFE_Y = 200
MOVE_TIMEOUT = 10

SET_X, SET_Y, VACUUM, START_P1 = 1, 2, 3, 4
AT_X, AT_Y, SOURCE1, SOURCE2 = 15, 16, 17, 18
P1_RUNNING, P2_RUNNING, P1_SENSOR, P2_SENSOR = 19, 20, 21, 22
WAIT_BEFORE_PICK = {
    "source1": (SOURCE1, 1),
    "source2": (SOURCE2, 1),
    "process1": (P1_RUNNING, 0),
    "process2": (P2_RUNNING, 0),
}

client = ModbusTcpClient(HOST, port=PORT)
crane = {"x": 0, "y": 0, "pos": None, "part": None, "next_id": 1}
parts_at = {}


def read_registers():
    return client.read_holding_registers(address=0, count=25).registers


def write_output(address, value):
    client.write_register(address, value)


def move_to(x, y):
    write_output(SET_X, x)
    write_output(SET_Y, y)
    deadline = time.time() + MOVE_TIMEOUT
    while read_registers()[AT_X:AT_Y + 1] != [x, y]:
        if time.time() > deadline:
            raise RuntimeError(f"Crane did not reach X={x} Y={y}, check the event log for a collision")
        time.sleep(0.1)
    crane["x"], crane["y"] = x, y
    if crane["part"]:
        log_position()


def travel_to(x, y):
    registers = read_registers()
    if registers[AT_X] != x:
        move_to(registers[AT_X], SAFE_Y)
        move_to(x, SAFE_Y)
    move_to(x, y)


def wait_until(address, value):
    while read_registers()[address] != value:
        time.sleep(0.2)


def pick_part():
    if crane["x"] in parts_at:
        crane["part"] = parts_at.pop(crane["x"])
    else:
        crane["part"] = crane["next_id"]
        crane["next_id"] += 1
    log_position()


def place_part():
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
        crane["pos"] = action["pos"]
        travel_to(positions[action["pos"]]["setX"], positions[action["pos"]]["setY"])
    if "vacuum" in action:
        if action["vacuum"] == 1 and crane["pos"] in WAIT_BEFORE_PICK:
            address, value = WAIT_BEFORE_PICK[crane["pos"]]
            wait_until(address, value)
        write_output(VACUUM, action["vacuum"])
        if action["vacuum"] == 1:
            pick_part()
        elif crane["part"]:
            place_part()
    if "process" in action:
        write_output(START_P1 + action["process"] - 1, 1)


def run_sequence(config, name):
    for action in config["sequences"][name]:
        run_action(action, config["positions"])


def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)


def choose_sequence(state, last_source):
    if state[P1_SENSOR] == 1 and state[P1_RUNNING] == 0:
        return "p1_to_sink"
    if state[P2_SENSOR] == 1 and state[P2_RUNNING] == 0 and state[P1_SENSOR] == 0:
        return "p2_to_p1"
    source1_ready = state[SOURCE1] == 1 and state[P1_SENSOR] == 0
    source2_ready = state[SOURCE2] == 1 and state[P2_SENSOR] == 0
    if source1_ready and (not source2_ready or last_source == "s2_to_p2"):
        return "s1_to_p1"
    if source2_ready:
        return "s2_to_p2"
    return None


def run_auto(config):
    last_source = None
    while True:
        name = choose_sequence(read_registers(), last_source)
        if name:
            print(name)
            run_sequence(config, name)
            if name in ("s1_to_p1", "s2_to_p2"):
                last_source = name
        else:
            time.sleep(0.2)


def main():
    config = load_config()
    start_log()
    if not client.connect():
        print(f"Could not connect to the simulation on {HOST}:{PORT}")
        return
    try:
        run_auto(config)
    except KeyboardInterrupt:
        print("Stopped")
    finally:
        client.close()


if __name__ == "__main__":
    main()
