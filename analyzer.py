import sys
import time
import shutil
import math
import threading
import socket
import select
import psutil

if sys.platform == "win32":
    import msvcrt
    import os
    os.system("")
else:
    msvcrt = None

sys.stdout.reconfigure(encoding="utf-8")

BLOCKS = [" ", " ", "▂", "▃", "▄", "▅", "▆", "▇", "█"]
WHITE = "\033[97m"
DIM = "\033[90m"
RESET = "\033[0m"

class NetworkMonitor:
    def __init__(self):
        self.lock = threading.Lock()
        self.connected = False
        self.speed = 0.0
        self.ping = 0.0
        self.active = True

    def start(self):
        threading.Thread(target=self._track_traffic, daemon=True).start()
        threading.Thread(target=self._track_ping, daemon=True).start()

    def _get_bytes(self):
        try:
            io = psutil.net_io_counters(pernic=True)
            return sum(
                s.bytes_recv + s.bytes_sent 
                for net, s in io.items() 
                if "loopback" not in net.lower() and not net.startswith("lo")
            )
        except Exception:
            return 0

    def _track_traffic(self):
        last_bytes = self._get_bytes()
        last_time = time.perf_counter()
        while self.active:
            time.sleep(0.12)
            now = time.perf_counter()
            curr_bytes = self._get_bytes()
            dt = max(0.001, now - last_time)
            if last_bytes > 0 and curr_bytes >= last_bytes:
                raw_speed = (((curr_bytes - last_bytes) / 1024.0) * 8.0) / dt
            else:
                raw_speed = 0.0
            last_bytes, last_time = curr_bytes, now
            with self.lock:
                self.speed = (self.speed * 0.4) + (raw_speed * 0.6)

    def _track_ping(self):
        while self.active:
            try:
                t0 = time.perf_counter()
                conn = socket.create_connection(('1.1.1.1', 53), timeout=0.5)
                ms = (time.perf_counter() - t0) * 1000.0
                conn.close()
                with self.lock:
                    self.ping = round(ms, 1)
                    self.connected = True
            except (socket.timeout, OSError):
                with self.lock:
                    self.ping = 0.0
                    self.connected = False
            time.sleep(0.25)

class TerminalVisualizer:
    def __init__(self):
        self.monitor = NetworkMonitor()
        self.monitor.start()
        self.history = []
        self.val = 0.0
        self.tick = 0
        self.width = 2

    def _check_input(self):
        if msvcrt:
            if msvcrt.kbhit():
                return msvcrt.getch()
        else:
            rlist, _, _ = select.select([sys.stdin], [], [], 0.0)
            if rlist:
                return sys.stdin.read(1).encode('utf-8')
        return None

    def run(self):
        sys.stdout.write("\033[?25l\033[2J")
        sys.stdout.flush()
        old_settings = None
        if not msvcrt:
            import termios
            import tty
            old_settings = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())
        try:
            while True:
                t0 = time.perf_counter()
                cols, lines = shutil.get_terminal_size((80, 24))
                self.tick += 1
                with self.monitor.lock:
                    connected = self.monitor.connected
                    speed = self.monitor.speed
                    ping = self.monitor.ping
                if not connected:
                    self.val *= 0.7
                else:
                    boost = min(0.5, math.log1p(speed) / 20.0)
                    penalty = 0.15 if ping > 120 else (0.05 if ping == 0 else 0.0)
                    target = max(0.05, min(1.0, 0.3 + boost - penalty))
                    self.val += (target - self.val) * 0.2
                bar_count = max(6, (cols - 2) // (self.width + 1))
                if len(self.history) != bar_count:
                    self.history = [self.val] * bar_count
                if self.tick % 2 == 0:
                    self.history.pop(0)
                    self.history.append(self.val)
                h = max(4, lines - 3)
                pad = max(0, (cols - (bar_count * (self.width + 1) - 1)) // 2)
                if connected:
                    if speed >= 1000.0:
                        speed_str = f"{speed / 1000.0:.1f} Mbps"
                    else:
                        speed_str = f"{speed:.0f} kbps"
                    header = f"{WHITE}Connected{RESET} {speed_str} {ping:.0f} ms"
                else:
                    header = f"{DIM}Disconnected 0 kbps -- ms{RESET}"
                
                controls = f"  {DIM}[Q]: Quit | [P]: Toggle Width ({self.width}){RESET}"
                buf = [" " * pad + header + controls]
                steps = [int(max(0, min(1, v)) * (h * 8)) for v in self.history]
                
                for r in range(h - 1, -1, -1):
                    row = [" " * pad]
                    floor = r * 8
                    for idx in range(bar_count):
                        diff = steps[idx] - floor
                        if diff >= 8:
                            char = "█" * self.width
                        elif diff <= 0:
                            char = " " * self.width
                        else:
                            char = BLOCKS[diff] * self.width
                        row.append(f"{WHITE}{char}{RESET}" + (" " if idx < bar_count - 1 else ""))
                    buf.append("".join(row))
                sys.stdout.write("\033[H" + "\n".join(buf))
                sys.stdout.flush()
                key = self._check_input()
                if key:
                    if key in (b"q", b"Q", b"\x03"):
                        break
                    elif key in (b"p", b"P"):
                        self.width = 1 if self.width == 2 else 2
                dt = time.perf_counter() - t0
                time.sleep(max(0.001, (1.0 / 60.0) - dt))
        except KeyboardInterrupt:
            pass
        finally:
            self.monitor.active = False
            if old_settings:
                import termios
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
            sys.stdout.write("\033[?25h\033[2J\033[H")
            sys.stdout.flush()

if __name__ == "__main__":
    TerminalVisualizer().run()
