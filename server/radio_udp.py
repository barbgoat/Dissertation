# server/radio_udp.py
import socket
import struct
import time
from typing import Dict, Optional, Tuple

from protocol import Beacon, Sack, encode, decode

# -----------------------
# Config
# -----------------------
# Uplink (nodes -> server) via UDP unicast
HOST = "0.0.0.0"
UL_PORT = 5000

# Downlink (server -> nodes) via UDP multicast
MCAST_GROUP = "239.1.2.3"
DL_PORT = 5001
MCAST_TTL = 1           # 1 = só rede local
MCAST_IFACE_IP = "0.0.0.0"  # IP da NIC para multicast (0.0.0.0 = default do SO)

# Superframe (tempo entre BEACON e SACK)
SUPERFRAME_DURATION_S = 10

# Parâmetros TS-LoRa (têm de bater certo com o nó)
NUM_SLOTS = 8
SLOT_DURATION_US = 1_000_000  # 1000 ms por slot
GUARD_US = 0                  # ex.: 10_000 para 10 ms

# Se True: só ACK se UL estiver dentro da janela do slot esperado
ENFORCE_SLOT_WINDOW = True

# -----------------------
# Time helpers
# -----------------------
def now_ms() -> int:
    return int(time.time() * 1000)

def now_us() -> int:
    return int(time.time() * 1_000_000)

def slot_window(sf_start_us: int, devaddr: int) -> Tuple[int, int, int, int, int]:
    """
    Retorna:
      slot, valid_start, valid_end, slot_start, slot_end
    """
    slot = int(devaddr) % int(NUM_SLOTS)
    slot_start = sf_start_us + slot * int(SLOT_DURATION_US)
    slot_end = slot_start + int(SLOT_DURATION_US)
    valid_start = slot_start + int(GUARD_US)
    valid_end = slot_end - int(GUARD_US)
    return slot, valid_start, valid_end, slot_start, slot_end

# -----------------------
# UDP sockets
# -----------------------
def make_ul_rx_socket() -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((HOST, UL_PORT))
    s.settimeout(0.5)
    return s

def make_dl_tx_socket() -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)

    # TTL multicast
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, struct.pack("b", int(MCAST_TTL)))

    # Interface multicast (opcional; útil se tiveres várias NICs)
    try:
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(MCAST_IFACE_IP))
    except OSError:
        pass

    # Não receber o próprio multicast na mesma máquina (opcional)
    try:
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 0)
    except OSError:
        pass

    return s

def send_multicast(tx_sock: socket.socket, payload: bytes) -> None:
    # 1 JSON por datagrama; mantém \n para compatibilidade com o teu framing antigo
    tx_sock.sendto(payload + b"\n", (MCAST_GROUP, DL_PORT))

# -----------------------
# Main
# -----------------------
def main() -> None:
    ul_rx = make_ul_rx_socket()
    dl_tx = make_dl_tx_socket()

    # Guarda o último endereço/porto visto por devaddr (útil se quiseres unicast respostas)
    last_seen: Dict[int, Tuple[str, int]] = {}

    sf_id = 0

    print(f"[{now_ms()} ms] UDP UL listening on {HOST}:{UL_PORT}")
    print(f"[{now_ms()} ms] UDP DL multicast to {MCAST_GROUP}:{DL_PORT} ttl={MCAST_TTL}")
    print(
        f"[{now_ms()} ms] Config: SUPERFRAME={SUPERFRAME_DURATION_S}s "
        f"NUM_SLOTS={NUM_SLOTS} SLOT_DUR={SLOT_DURATION_US}us GUARD={GUARD_US}us "
        f"ENFORCE_SLOT_WINDOW={ENFORCE_SLOT_WINDOW}"
    )

    while True:
        # ---------------------------
        # BEACON (sf_start em tempo "gateway")
        gw_ts = now_us()
        sf_start_us = gw_ts

        beacon = Beacon(sf_id=sf_id, gw_ts=gw_ts)
        beacon_b = encode(beacon)

        send_multicast(dl_tx, beacon_b)
        print(f"[{now_ms()} ms] [BEACON] SF {sf_id} gw_ts(us)={gw_ts}")

        # ---------------------------
        # UL collection durante o SF
        uplinks: Dict[int, dict] = {}  # só guarda ULs aceites
        t0 = time.time()

        while (time.time() - t0) < SUPERFRAME_DURATION_S:
            try:
                data, addr = ul_rx.recvfrom(4096)
            except socket.timeout:
                continue
            except Exception as e:
                print(f"[{now_ms()} ms] [UDP] recv error: {e}")
                continue

            line = data.strip()
            if not line:
                continue

            msg = decode(line)
            if msg is None:
                continue

            devaddr = msg.get("devaddr")
            if devaddr is None:
                continue

            try:
                dev_i = int(devaddr)
            except Exception:
                continue

            last_seen[dev_i] = addr

            # Para validação temporal precisamos de tx_end_ts (em tempo de rede)
            tx_end_ts = msg.get("tx_end_ts")

            if (not ENFORCE_SLOT_WINDOW) or (tx_end_ts is None):
                uplinks[dev_i] = msg
                print(f"[{now_ms()} ms] [UL] from {dev_i} addr={addr} msg={msg}")
                continue

            try:
                tx_end_ts_i = int(tx_end_ts)
            except Exception:
                print(f"[{now_ms()} ms] [DROP] dev={dev_i} invalid tx_end_ts={tx_end_ts}")
                continue

            slot, v0, v1, s0, s1 = slot_window(sf_start_us, dev_i)
            ok = (v0 <= tx_end_ts_i <= v1)
            delta_us = tx_end_ts_i - sf_start_us

            offset_measured_us = tx_end_ts_i - s0

            status = "IN"
            diff_us = 0
            if tx_end_ts_i < v0:
                status = "EARLY"
                diff_us = v0 - tx_end_ts_i
            elif tx_end_ts_i > v1:
                status = "LATE"
                diff_us = tx_end_ts_i - v1

            print(
                f"[{now_ms()} ms] [ULCHK] dev={dev_i} slot={slot} "
                f"delta_us={delta_us} offset_measured_us={offset_measured_us} "
                f"status={status} diff_us={diff_us} "
                f"win=[{v0},{v1}] slot=[{s0},{s1}] addr={addr}"
            )

            if ok:
                uplinks[dev_i] = msg
                print(f"[{now_ms()} ms] [UL] from {dev_i} msg={msg}")
            else:
                print(f"[{now_ms()} ms] [DROP] dev={dev_i} {status} by {diff_us} us")

        # ---------------------------
        # SACK (ACK só dos ULs aceites) -> multicast
        acked = sorted(list(uplinks.keys()))
        sack = Sack(sf_id=sf_id, acked_nodes=acked)
        sack_b = encode(sack)

        send_multicast(dl_tx, sack_b)
        print(f"[{now_ms()} ms] [SACK] ACK {acked}")

        sf_id += 1


if __name__ == "__main__":
    main()