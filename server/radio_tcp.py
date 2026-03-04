# server/radio_tcp.py
import socket
import time
from typing import Dict, List, Optional, Tuple

from protocol import Beacon, Sack, encode, decode

HOST = "0.0.0.0"
PORT = 5000

# Superframe (tempo entre BEACON e SACK)
SUPERFRAME_DURATION_S = 10

# Parâmetros TS-LoRa (têm de bater certo com o nó)
NUM_SLOTS = 8
SLOT_DURATION_US = 1_000_000  # 1000 ms por slot
GUARD_US = 0                  # ex.: 10_000 para 10 ms

# Se True: só ACK se UL estiver dentro da janela do slot esperado
ENFORCE_SLOT_WINDOW = True


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


class Client:
    def __init__(self, sock: socket.socket, addr: Tuple[str, int]):
        self.sock = sock
        self.addr = addr
        self.sock.setblocking(False)
        self.buf = b""

    def close(self) -> None:
        try:
            self.sock.close()
        except Exception:
            pass

    def send_line(self, payload: bytes) -> None:
        # 1 JSON por linha
        self.sock.sendall(payload + b"\n")

    def recv_lines(self) -> List[bytes]:
        lines: List[bytes] = []
        try:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("disconnected")
            self.buf += chunk
        except BlockingIOError:
            return []
        except Exception:
            raise

        while b"\n" in self.buf:
            line, self.buf = self.buf.split(b"\n", 1)
            line = line.strip()
            if line:
                lines.append(line)
        return lines


def main() -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(8)
    server.setblocking(False)

    clients: List[Client] = []
    sf_id = 0

    print(f"[{now_ms()} ms] TCP Gateway listening on {HOST}:{PORT}")
    print(
        f"[{now_ms()} ms] Config: SUPERFRAME={SUPERFRAME_DURATION_S}s "
        f"NUM_SLOTS={NUM_SLOTS} SLOT_DUR={SLOT_DURATION_US}us GUARD={GUARD_US}us "
        f"ENFORCE_SLOT_WINDOW={ENFORCE_SLOT_WINDOW}"
    )

    while True:
        # aceitar novas conexões
        while True:
            try:
                sock, addr = server.accept()
                c = Client(sock, addr)
                clients.append(c)
                print(f"[{now_ms()} ms] [TCP] Node connected: {addr}")
            except BlockingIOError:
                break
            except Exception as e:
                print(f"[{now_ms()} ms] [TCP] accept error: {e}")
                break

        if not clients:
            time.sleep(0.05)
            continue

        # ---------------------------
        # BEACON (sf_start em tempo "gateway")
        gw_ts = now_us()
        sf_start_us = gw_ts

        beacon = Beacon(sf_id=sf_id, gw_ts=gw_ts)
        beacon_b = encode(beacon)

        dead: List[Client] = []
        for c in clients:
            try:
                c.send_line(beacon_b)
            except Exception:
                dead.append(c)
        for c in dead:
            print(f"[{now_ms()} ms] [TCP] Node disconnected: {c.addr}")
            c.close()
            try:
                clients.remove(c)
            except ValueError:
                pass

        print(f"[{now_ms()} ms] [BEACON] SF {sf_id} gw_ts(us)={gw_ts}")

        # ---------------------------
        # UL collection durante o SF
        uplinks: Dict[int, dict] = {}  # só guarda ULs aceites (ok dentro do slot)
        t0 = time.time()

        while (time.time() - t0) < SUPERFRAME_DURATION_S:
            # aceitar novos durante SF
            while True:
                try:
                    sock, addr = server.accept()
                    c = Client(sock, addr)
                    clients.append(c)
                    print(f"[{now_ms()} ms] [TCP] Node connected: {addr}")
                except BlockingIOError:
                    break
                except Exception:
                    break

            dead = []
            for c in list(clients):
                try:
                    for line in c.recv_lines():
                        msg = decode(line)
                        if msg is None:
                            continue

                        devaddr = msg.get("devaddr")
                        if devaddr is None:
                            continue

                        # Para validação temporal precisamos de tx_end_ts (em tempo de rede)
                        tx_end_ts = msg.get("tx_end_ts")

                        if (not ENFORCE_SLOT_WINDOW) or (tx_end_ts is None):
                            uplinks[int(devaddr)] = msg
                            print(f"[{now_ms()} ms] [UL] from {devaddr} msg={msg}")
                            continue

                        try:
                            tx_end_ts_i = int(tx_end_ts)
                        except Exception:
                            print(f"[{now_ms()} ms] [DROP] dev={devaddr} invalid tx_end_ts={tx_end_ts}")
                            continue

                        slot, v0, v1, s0, s1 = slot_window(sf_start_us, int(devaddr))
                        ok = (v0 <= tx_end_ts_i <= v1)
                        delta_us = tx_end_ts_i - sf_start_us

                        # NOVO: offset dentro do slot (medido a partir do slot_start)
                        offset_measured_us = tx_end_ts_i - s0

                        # NOVO: classificar early/late e quantificar (µs)
                        status = "IN"
                        diff_us = 0
                        if tx_end_ts_i < v0:
                            status = "EARLY"
                            diff_us = v0 - tx_end_ts_i
                        elif tx_end_ts_i > v1:
                            status = "LATE"
                            diff_us = tx_end_ts_i - v1

                        print(
                            f"[{now_ms()} ms] [ULCHK] dev={devaddr} slot={slot} "
                            f"delta_us={delta_us} offset_measured_us={offset_measured_us} "
                            f"status={status} diff_us={diff_us} "
                            f"win=[{v0},{v1}] slot=[{s0},{s1}]"
                        )

                        if ok:
                            uplinks[int(devaddr)] = msg
                            print(f"[{now_ms()} ms] [UL] from {devaddr} msg={msg}")
                        else:
                            print(f"[{now_ms()} ms] [DROP] dev={devaddr} {status} by {diff_us} us")
                except Exception:
                    dead.append(c)

            for c in dead:
                print(f"[{now_ms()} ms] [TCP] Node disconnected: {c.addr}")
                c.close()
                try:
                    clients.remove(c)
                except ValueError:
                    pass

            time.sleep(0.002)

        # ---------------------------
        # SACK (ACK só dos ULs aceites)
        acked = sorted(list(uplinks.keys()))
        sack = Sack(sf_id=sf_id, acked_nodes=acked)
        sack_b = encode(sack)

        dead = []
        for c in clients:
            try:
                c.send_line(sack_b)
            except Exception:
                dead.append(c)
        for c in dead:
            print(f"[{now_ms()} ms] [TCP] Node disconnected: {c.addr}")
            c.close()
            try:
                clients.remove(c)
            except ValueError:
                pass

        print(f"[{now_ms()} ms] [SACK] ACK {acked}")
        sf_id += 1


if __name__ == "__main__":
    main()