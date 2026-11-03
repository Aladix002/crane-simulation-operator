import csv  # zapis logu do CSV suboru
import json  # nacitanie crane.json (pozicie a sekvencie)
import time  # time.sleep pri cakani
from datetime import datetime  # cas pre kazdy riadok v logu
from pathlib import Path  # cesty k suborom vedla tohto skriptu

from pymodbus.client import ModbusTcpClient  # Modbus TCP klient na komunikaciu so simulaciou

HOST = "127.0.0.1"  # simulacia bezi na tomto pocitaci
PORT = 5020  # port simulacie na Ubuntu
CONFIG_FILE = Path(__file__).parent / "crane.json"  # konfiguracia v rovnakom priecinku ako b.py
LOG_FILE = Path(__file__).parent / "log.csv"  # sem sa zapisuje pohyb dielov
SAFE_Y = 150  # bezpecna vyska na presun do strany: steny maju vrch 115 + neseny diel visi 25 pod chnapkou = min 140

SET_X, SET_Y, VACUUM, START_P1 = 1, 2, 3, 4  # vystupne registre: cielove X, cielove Y, vakuum, start procesu 1 (proces 2 je 5)
AT_X, AT_Y, SOURCE1, SOURCE2 = 15, 16, 17, 18  # vstupne registre: aktualne X, Y a ci je diel v zdroji 1 / 2
P1_RUNNING, P2_RUNNING, P1_SENSOR, P2_SENSOR = 19, 20, 21, 22  # ci proces bezi a ci v nom lezi diel
WAIT_BEFORE_PICK = {  # pred zdvihnutim z tejto pozicie pockaj, kym register (adresa) nema danu hodnotu
    "source1": (SOURCE1, 1),  # zo zdroja 1 dvihaj az ked tam diel je
    "source2": (SOURCE2, 1),  # zo zdroja 2 dvihaj az ked tam diel je
    "process1": (P1_RUNNING, 0),  # z procesu 1 dvihaj az ked dobehne
    "process2": (P2_RUNNING, 0),  # z procesu 2 dvihaj az ked dobehne
}

client = ModbusTcpClient(HOST, port=PORT)  # vytvori klienta, pripoji sa az v main()
crane = {"x": 0, "y": 0, "pos": None, "part": None, "next_id": 1}  # stav zeriavu: poloha, nazov pozicie, ID drzaneho dielu, dalsie volne ID
parts_at = {}  # ktory diel (ID) lezi na ktorom X, aby si diel drzal svoje ID medzi procesmi


def read_registers():  # precita naraz vsetkych 25 registrov simulacie
    return client.read_holding_registers(address=0, count=25).registers  # vrati zoznam, index = adresa registra


def write_output(address, value):  # zapise jednu hodnotu do registra
    client.write_register(address, value)  # napr. write_output(VACUUM, 1) zapne vakuum


def move_to(x, y):  # posle zeriav na (x, y) a pocka, kym tam dojde
    write_output(SET_X, x)  # ciel X
    write_output(SET_Y, y)  # ciel Y
    while read_registers()[AT_X:AT_Y + 1] != [x, y]:  # kym aktualna poloha [X, Y] nie je ciel
        time.sleep(0.1)  # kratko pockaj a skontroluj znova
    crane["x"], crane["y"] = x, y  # zapamataj si novu polohu
    if crane["part"]:  # ak prave nesie diel
        log_position()  # zapis tento bod do logu


def travel_to(x, y):  # bezpecny presun: hore, do strany, dole
    registers = read_registers()  # zisti, kde zeriav prave je
    if registers[AT_X] != x:  # ak sa musi posunut do strany
        move_to(registers[AT_X], SAFE_Y)  # najprv zvisle hore na bezpecnu vysku
        move_to(x, SAFE_Y)  # potom vodorovne nad ciel
    move_to(x, y)  # nakoniec dole na cielovu vysku


def wait_until(address, value):  # caka, kym register nadobudne danu hodnotu
    while read_registers()[address] != value:  # kym este nie je
        time.sleep(0.2)  # pockaj a skus znova


def pick_part():  # vola sa po zapnuti vakua, urci ID zdvihnuteho dielu
    if crane["x"] in parts_at:  # ak na tomto mieste uz lezi znamy diel (v procese)
        crane["part"] = parts_at.pop(crane["x"])  # zober jeho ID a odstran ho z miesta
    else:  # inak je to novy diel zo zdroja
        crane["part"] = crane["next_id"]  # prirad mu nove ID
        crane["next_id"] += 1  # dalsi novy diel dostane o 1 vacsie ID
    log_position()  # zapis bod, kde bol diel zdvihnuty


def place_part():  # vola sa po vypnuti vakua, diel ostane lezat na tomto X
    parts_at[crane["x"]] = crane["part"]  # zapamataj si, ze tu lezi tento diel
    crane["part"] = None  # zeriav uz nic nenesie


def start_log():  # vytvori novy log.csv len s hlavickou (stary sa prepise)
    with open(LOG_FILE, "w", newline="") as f:  # "w" = prepisat subor
        csv.writer(f).writerow(["product_id", "timestamp", "x", "y", "vacuum"])  # nazvy stlpcov


def log_position():  # prida do logu jeden riadok s aktualnym dielom a polohou
    timestamp = datetime.now().isoformat(timespec="seconds")  # aktualny cas, napr. 2026-11-03T14:05:12
    with open(LOG_FILE, "a", newline="") as f:  # "a" = pridat na koniec suboru
        csv.writer(f).writerow([crane["part"], timestamp, crane["x"], crane["y"], 1])  # vakuum je vzdy 1, lebo loguje len ked nesie diel


def run_action(action, positions):  # vykona jeden krok sekvencie, napr. {"pos": "source1"} alebo {"vacuum": 1}
    if "pos" in action:  # krok = chod na poziciu
        crane["pos"] = action["pos"]  # zapamataj si nazov pozicie (potrebne pre WAIT_BEFORE_PICK)
        travel_to(positions[action["pos"]]["setX"], positions[action["pos"]]["setY"])  # zober X a Y z crane.json a chod tam
    if "vacuum" in action:  # krok = zapni / vypni vakuum
        if action["vacuum"] == 1 and crane["pos"] in WAIT_BEFORE_PICK:  # ak ideme dvihat z miesta, kde treba cakat
            address, value = WAIT_BEFORE_PICK[crane["pos"]]  # ktory register a aku hodnotu cakame
            wait_until(address, value)  # pockaj (napr. kym proces dobehne)
        write_output(VACUUM, action["vacuum"])  # zapni (1) alebo vypni (0) vakuum v simulacii
        if action["vacuum"] == 1:  # zapnute vakuum = zdvihol diel
            pick_part()  # urci ID dielu a zaloguj
        elif crane["part"]:  # vypnute vakuum a nieco niesol = polozil diel
            place_part()  # zapamataj, kde diel lezi
    if "process" in action:  # krok = spusti proces
        write_output(START_P1 + action["process"] - 1, 1)  # proces 1 -> register 4, proces 2 -> register 5


def run_sequence(config, name):  # vykona celu sekvenciu z crane.json podla nazvu
    for action in config["sequences"][name]:  # postupne kazdy krok
        run_action(action, config["positions"])  # vykonaj krok s poziciami z konfigu


def load_config():  # nacita crane.json
    with open(CONFIG_FILE) as f:  # otvori subor na citanie
        return json.load(f)  # vrati dict s "positions" a "sequences"


def choose_sequence(state, last_source):  # rozhodne, ktoru sekvenciu spustit teraz (alebo None)
    if state[P1_SENSOR] == 1 and state[P1_RUNNING] == 0:  # v P1 lezi hotovy diel
        return "p1_to_sink"  # najvyssia priorita: uvolni P1 a daj diel do sinku
    if state[P2_SENSOR] == 1 and state[P2_RUNNING] == 0 and state[P1_SENSOR] == 0:  # P2 hotovy a P1 je volny
        return "p2_to_p1"  # presun diel z P2 do P1
    source1_ready = state[SOURCE1] == 1 and state[P1_SENSOR] == 0  # v zdroji 1 je diel a P1 je volny
    source2_ready = state[SOURCE2] == 1 and state[P2_SENSOR] == 0  # v zdroji 2 je diel a P2 je volny
    if source1_ready and (not source2_ready or last_source == "s2_to_p2"):  # zdroj 1 ak je jediny pripraveny, alebo naposledy isiel zdroj 2
        return "s1_to_p1"  # diel zo zdroja 1 do P1
    if source2_ready:  # inak zdroj 2, ak je pripraveny
        return "s2_to_p2"  # diel zo zdroja 2 do P2
    return None  # nic sa neda robit, pockaj


def run_auto(config):  # hlavna nekonecna slucka automatickeho rezimu
    last_source = None  # ktory zdroj bol obsluzeny naposledy (na striedanie)
    while True:  # bezi, kym ho nezastavis Ctrl+C
        name = choose_sequence(read_registers(), last_source)  # precitaj stav a vyber sekvenciu
        if name:  # ak je co robit
            print(name)  # vypis nazov sekvencie do terminalu
            run_sequence(config, name)  # vykonaj ju
            if name in ("s1_to_p1", "s2_to_p2"):  # ak to bola sekvencia zo zdroja
                last_source = name  # zapamataj si ju, aby nabuduce isiel druhy zdroj
        else:  # nic na robenie
            time.sleep(0.2)  # chvilu pockaj a skontroluj znova


def main():  # start programu
    config = load_config()  # nacitaj pozicie a sekvencie
    start_log()  # zaloz novy log.csv
    if not client.connect():  # skus sa pripojit k simulacii
        print(f"Could not connect to the simulation on {HOST}:{PORT}")  # simulacia nebezi
        return  # skonci
    try:  # spusti automaticky rezim
        run_auto(config)  # bezi donekonecna
    except KeyboardInterrupt:  # Ctrl+C
        print("Stopped")  # vypis, ze sa zastavil
    finally:  # vzdy na konci
        client.close()  # zatvor spojenie so simulaciou


if __name__ == "__main__":  # len ked spustis python b.py (nie pri importe)
    main()  # spusti program
