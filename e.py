import json
import time
from pathlib import Path

from pymodbus.client import ModbusTcpClient

CONFIG_FILE = Path(__file__).parent / "crane.json"
SAFE_Y = 150

SET_X, SET_Y, VACUUM, START_P1 = 1, 2, 3, 4
AT_X, AT_Y, SOURCE1, P1_RUNNING = 15, 16, 17, 19
WAIT_BEFORE_PICK = {
    "source1": (SOURCE1, 1),
    "process1": (P1_RUNNING, 0),
}

client = ModbusTcpClient("127.0.0.1", port=5020)
crane = {"position": None}


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


def run_action(action, positions):
    if "position" in action:
        crane["position"] = action["position"]
        move_to(positions[action["position"]]["setX"], positions[action["position"]]["setY"])
    if "vacuum" in action:
        if action["vacuum"] == 1 and crane["position"] in WAIT_BEFORE_PICK:
            address, value = WAIT_BEFORE_PICK[crane["position"]]
            while read_registers()[address] != value:
                time.sleep(0.2)
        write_output(VACUUM, action["vacuum"])
    if "process" in action:
        write_output(START_P1 + action["process"] - 1, 1)


def main():
    with open(CONFIG_FILE) as f:
        config = json.load(f)
    if not client.connect():
        print("Could not connect to the simulation on 127.0.0.1:5020")
        return
    try:
        for action in config["sequences"]["s1_to_p1_to_sink"]:
            run_action(action, config["positions"])
    except KeyboardInterrupt:
        print("Stopped")
    finally:
        client.close()


if __name__ == "__main__":
    main()
