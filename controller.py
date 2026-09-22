import json
import time
from pathlib import Path

from pymodbus.client import ModbusTcpClient

HOST = "127.0.0.1"
PORT = 5020
CONFIG_FILE = Path(__file__).parent / "cell.json"
MOVE_TIMEOUT = 15

RESET, SET_X, SET_Y, VACUUM, START_P1, START_P2 = 0, 1, 2, 3, 4, 5
AT_X, AT_Y = 15, 16

client = ModbusTcpClient(HOST, port=PORT)


def read_input(address):
    result = client.read_holding_registers(address=address, count=1)
    return result.registers[0]


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


def run_action(action, positions):
    if "pos" in action:
        action = positions[action["pos"]]
    if "setX" in action:
        move_to(action["setX"], action["setY"])
    if "vacuum" in action:
        write_output(VACUUM, action["vacuum"])
    if "process" in action:
        write_output(START_P1 + action["process"] - 1, 1)


def run_sequence(config, name):
    for action in config["sequences"][name]:
        print(action)
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
        run_sequence(config, "grade_e")
    finally:
        client.close()


if __name__ == "__main__":
    main()
