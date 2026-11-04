import csv
import json
import time
from datetime import datetime
from pathlib import Path
from pymodbus.client import ModbusTcpClient

CONFIG_FILE = Path(__file__).parent / "crane.json"
LOG_FILE = Path(__file__).parent / "log.csv"
SAFE_Y = 150

SET_X, SET_Y, VACUUM, START_P1 = 1, 2, 3, 4
AT_X, AT_Y, SOURCE1, SOURCE2 = 15, 16, 17, 18
P1_RUNNING, P2_RUNNING, P1_SENSOR, P2_SENSOR = 19, 20, 21, 22

client = ModbusTcpClient("127.0.0.1", port=5020)
crane = {"x": 0, "y": 0, "part": None, "next_id": 1}
parts_at = {}


def read_registers():
    return client.read_holding_registers(address=0, count=25).registers


def write_output(address, value):
    client.write_register(address, value)


def move_to(x, y):
    current_x = read_registers()[AT_X]
    if current_x == x:
        points = [(x, y)]
    else:
        points = [(current_x, SAFE_Y), (x, SAFE_Y), (x, y)]
    for point_x, point_y in points:
        write_output(SET_X, point_x)
        write_output(SET_Y, point_y)
        while read_registers()[AT_X:AT_Y + 1] != [point_x, point_y]:
            time.sleep(0.1)
        crane["x"], crane["y"] = point_x, point_y
        if crane["part"]:
            log_position()


def log_position():
    timestamp = datetime.now().isoformat(timespec="seconds")
    with open(LOG_FILE, "a", newline="") as f:
        csv.writer(f).writerow([crane["part"], timestamp, crane["x"], crane["y"], 1])


def run_action(action, positions):
    if "position" in action:
        move_to(positions[action["position"]]["setX"], positions[action["position"]]["setY"])
    if "vacuum" in action:
        write_output(VACUUM, action["vacuum"])
        if action["vacuum"] == 1:
            if crane["x"] in parts_at:
                crane["part"] = parts_at.pop(crane["x"])
            else:
                crane["part"] = crane["next_id"]
                crane["next_id"] += 1
                log_position()
        elif crane["part"]:
            parts_at[crane["x"]] = crane["part"]
            crane["part"] = None
    if "process" in action:
        write_output(START_P1 + action["process"] - 1, 1)


def choose_sequence(registers, last_source_sequence):
    if registers[P1_SENSOR] == 1 and registers[P1_RUNNING] == 0:
        return "p1_to_sink"
    if registers[P2_SENSOR] == 1 and registers[P2_RUNNING] == 0 and registers[P1_SENSOR] == 0:
        return "p2_to_p1"
    source1_ready = registers[SOURCE1] == 1 and registers[P1_SENSOR] == 0
    source2_ready = registers[SOURCE2] == 1 and registers[P2_SENSOR] == 0
    if source1_ready and (not source2_ready or last_source_sequence == "s2_to_p2"):
        return "s1_to_p1"
    if source2_ready:
        return "s2_to_p2"
    return None


def run_auto(config):
    last_source_sequence = None
    while True:
        sequence_name = choose_sequence(read_registers(), last_source_sequence)
        if sequence_name:
            print(sequence_name)
            for action in config["sequences"][sequence_name]:
                run_action(action, config["positions"])
            if sequence_name in ("s1_to_p1", "s2_to_p2"):
                last_source_sequence = sequence_name
        else:
            time.sleep(0.2)


def main():
    with open(CONFIG_FILE) as f:
        config = json.load(f)
    with open(LOG_FILE, "w", newline="") as f:
        csv.writer(f).writerow(["product_id", "timestamp", "x", "y", "vacuum"])
    if not client.connect():
        print("Could not connect to the simulation on 127.0.0.1:5020")
        return
    try:
        run_auto(config)
    except KeyboardInterrupt:
        print("Stopped")
    finally:
        client.close()


if __name__ == "__main__":
    main()
