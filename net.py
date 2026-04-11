import struct

try:
    from time import ticks_ms, ticks_diff
except ImportError:
    from time import time as _t
    def ticks_ms():
        return int(_t() * 1000)
    def ticks_diff(a, b):
        return a - b

try:
    import espnow
    import network
    _HAS_NET = True
except ImportError:
    _HAS_NET = False

BCAST = b'\xff\xff\xff\xff\xff\xff'
PKT_POS = 0x01
PKT_DMG = 0x02
PEER_TIMEOUT = 6000
ANGLE_SCALE = 10430.378


class NetManager:
    def __init__(self):
        self.peers = {}
        self._e = None
        self.rx_count = 0
        if _HAS_NET:
            try:
                sta = network.WLAN(network.STA_IF)
                sta.active(True)
                try:
                    sta.disconnect()
                except Exception:
                    pass
                try:
                    sta.config(channel=1)
                except Exception:
                    pass
                self._e = espnow.ESPNow()
                self._e.active(True)
                self._e.add_peer(BCAST)
            except Exception:
                self._e = None

    def broadcast(self, name, x, y, angle, health, flags):
        if not self._e:
            return
        nb = (name.encode()[:6] + b'\x00\x00\x00\x00\x00\x00')[:6]
        xi = int(x * 256) & 0xFFFF
        yi = int(y * 256) & 0xFFFF
        ai = int(angle * ANGLE_SCALE) & 0xFFFF
        pkt = struct.pack('<B6sHHHBB', PKT_POS, nb, xi, yi, ai,
                          min(255, max(0, int(health))), flags & 0xFF)
        try:
            self._e.send(BCAST, pkt, False)
        except Exception:
            pass

    def receive(self, my_name):
        if not self._e:
            return 0
        damage = 0
        now = ticks_ms()

        for _ in range(10):
            if not self._e.any():
                break
            try:
                mac, data = self._e.irecv(0)
            except Exception:
                break
            if mac is None or data is None or len(data) < 2:
                continue

            self.rx_count += 1
            pt = data[0]
            if pt == PKT_POS and len(data) >= 15:
                _, nb, xi, yi, ai, hp, fl = struct.unpack(
                    '<B6sHHHBB', data[:15])
                try:
                    pname = nb.rstrip(b'\x00').decode('utf-8')
                except Exception:
                    pname = 'anon'
                mk = bytes(mac)
                if mk == bytes(b'\x00\x00\x00\x00\x00\x00'):
                    continue
                self.peers[mk] = {
                    'name': pname,
                    'x': xi / 256.0,
                    'y': yi / 256.0,
                    'angle': ai / ANGLE_SCALE,
                    'health': hp,
                    'flags': fl,
                    'time': now,
                    'hit': 0,
                }
            elif pt == PKT_DMG and len(data) >= 8:
                _, tb, dmg = struct.unpack('<B6sB', data[:8])
                try:
                    target = tb.rstrip(b'\x00').decode('utf-8').strip()
                except Exception:
                    target = ''
                if target == my_name.strip():
                    damage += dmg

        expired = [k for k, v in self.peers.items()
                   if ticks_diff(now, v['time']) > PEER_TIMEOUT]
        for k in expired:
            del self.peers[k]

        return damage

    def send_damage(self, target_name, dmg):
        if not self._e:
            return
        tb = (target_name.encode()[:6] + b'\x00\x00\x00\x00\x00\x00')[:6]
        pkt = struct.pack('<B6sB', PKT_DMG, tb, min(255, dmg))
        try:
            self._e.send(BCAST, pkt, False)
        except Exception:
            pass

    def get_peers(self):
        return list(self.peers.values())

    def close(self):
        if self._e:
            try:
                self._e.active(False)
            except Exception:
                pass
