import time
from typing import Dict

from protocol import Beacon, Sack, encode, decode
from radio_io import RadioIO

SUPERFRAME_DURATION_S = 10


def now_ms() -> int:
    return int(time.time() * 1000)


def send_beacon(radio: RadioIO, sf_id: int) -> None:
    beacon = Beacon(sf_id=sf_id, gw_ts=radio.timestamp_us())
    radio.send(encode(beacon))
    print(f"[{now_ms()} ms] [BEACON] SF {sf_id}")


def collect_uplinks(radio: RadioIO, duration_s: int) -> Dict[int, dict]:
    uplinks: Dict[int, dict] = {}
    t0 = time.time()

    while (time.time() - t0) < duration_s:
        data = radio.receive()
        if not data:
            time.sleep(0.002)  # reduz CPU (evita busy-loop)
            continue

        msg = decode(data)
        if msg is None:
            continue

        devaddr = msg.get("devaddr")
        if devaddr is None:
            continue

        uplinks[int(devaddr)] = msg
        print(f"[{now_ms()} ms] [UL] from {devaddr} msg={msg}")

    return uplinks


def send_sack(radio: RadioIO, sf_id: int, uplinks: Dict[int, dict]) -> None:
    acked = sorted(list(uplinks.keys()))
    sack = Sack(sf_id=sf_id, acked_nodes=acked)
    radio.send(encode(sack))
    print(f"[{now_ms()} ms] [SACK] ACK {acked}")


def main() -> None:
    radio = RadioIO(port="COM3", baud=115200)

    print(f"[{now_ms()} ms] Server start: waiting 2s for ESP32 boot...")
    time.sleep(2)

    sf_id = 0

    try:
        while True:
            send_beacon(radio, sf_id)
            uplinks = collect_uplinks(radio, SUPERFRAME_DURATION_S)
            send_sack(radio, sf_id, uplinks)
            sf_id += 1
    finally:
        radio.close()


if __name__ == "__main__":
    main()