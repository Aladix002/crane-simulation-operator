import json
import time
from pathlib import Path

from pymodbus.client import ModbusTcpClient

HOST = "127.0.0.1"
PORT = 5020
CONFIG_FILE = Path(__file__).parent / "crane.json"
SAFE_Y = 150

SET_X, SET_Y, VACUUM, START_P1 = 1, 2, 3, 4
AT_X, AT_Y, SOURCE1, P1_RUNNING = 15, 16, 17, 19
WAIT_BEFORE_PICK = {
    "source1": (SOURCE1, 1),
    "process1": (P1_RUNNING, 0),
}

client = ModbusTcpClient(HOST, port=PORT)
crane = {"pos": None}


def read_registers():
    return client.read_holding_registers(address=0, count=25).registers


def write_output(address, value):
    client.write_register(address, value)


def move_to(x, y):
    write_output(SET_X, x)
    write_output(SET_Y, y)
    while read_registers()[AT_X:AT_Y + 1] != [x, y]:
        time.sleep(0.1)


def travel_to(x, y):
    registers = read_registers()
    if registers[AT_X] != x:
        move_to(registers[AT_X], SAFE_Y)
        move_to(x, SAFE_Y)
    move_to(x, y)


def wait_until(address, value):
    while read_registers()[address] != value:
        time.sleep(0.2)


def run_action(action, positions):
    if "pos" in action:
        crane["pos"] = action["pos"]
        travel_to(positions[action["pos"]]["setX"], positions[action["pos"]]["setY"])
    if "vacuum" in action:
        if action["vacuum"] == 1 and crane["pos"] in WAIT_BEFORE_PICK:
            address, value = WAIT_BEFORE_PICK[crane["pos"]]
            wait_until(address, value)
        write_output(VACUUM, action["vacuum"])
    if "process" in action:
        write_output(START_P1 + action["process"] - 1, 1)


def run_sequence(config, name):
    for action in config["sequences"][name]:
        run_action(action, config["positions"])


def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)


def main():
    config = load_config()
    if not client.connect():
        print(f"Could not connect to the simulation on {HOST}:{PORT}")
        return
    try:
        run_sequence(config, "s1_to_p1_to_sink")
    except KeyboardInterrupt:
        print("Stopped")
    finally:
        client.close()


if __name__ == "__main__":
    main()
