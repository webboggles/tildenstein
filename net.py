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

# Badge OS ESP-NOW service (firmware 2.1.x+). It is the single owner of the
# radio: it registers the broadcast peer, keeps the radio awake while apps are
# subscribed, and re-emits inbound packets as EspNowReceiveEvent. Apps that
# create their own espnow.ESPNow() clash with it (ESP_ERR_ESPNOW_EXIST) and get
# no traffic, so prefer the service when it exists.
try:
    from system.espnow import (
        espnow_service, BROADCAST_MAC, EspNowReceiveEvent)
    _HAS_OS_ESPNOW = True
except ImportError:
    _HAS_OS_ESPNOW = False
    BROADCAST_MAC = b'\xff\xff\xff\xff\xff\xff'

BCAST = b'\xff\xff\xff\xff\xff\xff'
PKT_POS = 0x01
PKT_DMG = 0x02
PEER_TIMEOUT = 6000
ANGLE_SCALE = 10430.378
CHANNEL = 1
RELOCK_INT = 2000
ZERO_MAC = b'\x00\x00\x00\x00\x00\x00'


class NetManager:
    def __init__(self, app=None):
        self.peers = {}
        self.rx_count = 0
        self._app = app
        self._os = None
        self._e = None
        self._sta = None
        self._lock_t = ticks_ms()
        self._inbox = []

        # Preferred path: subscribe to the OS ESP-NOW service. Subscribing
        # also flags us as a listener so the OS keeps the radio awake.
        if _HAS_OS_ESPNOW and app is not None:
            try:
                espnow_service.subscribe(self._on_rx, app)
                self._os = espnow_service
            except Exception:
                self._os = None

        # Legacy path for firmware without the OS service.
        if self._os is None and _HAS_NET:
            try:
                ap = network.WLAN(network.AP_IF)
                try:
                    ap.active(False)
                except Exception:
                    pass
                sta = network.WLAN(network.STA_IF)
                sta.active(True)
                self._sta = sta
                try:
                    sta.config(pm=sta.PM_NONE)
                except Exception:
                    pass
                self._lock_channel()
                self._e = espnow.ESPNow()
                self._e.active(True)
                try:
                    self._e.add_peer(BCAST)
                except Exception:
                    pass
            except Exception:
                self._e = None

    def _on_rx(self, event):
        # Called from the eventbus when the OS service receives a packet.
        try:
            self._inbox.append((bytes(event.mac), bytes(event.msg)))
        except Exception:
            pass

    def _lock_channel(self):
        # Legacy-only: the OS keeps scanning for wifi, hopping the radio
        # channel. Disconnect and pin the channel so badges converge.
        sta = self._sta
        if not sta:
            return
        try:
            sta.disconnect()
        except Exception:
            pass
        try:
            sta.config(reconnects=0)
        except Exception:
            pass
        try:
            sta.config(channel=CHANNEL)
        except Exception:
            pass

    def broadcast(self, name, x, y, angle, health, flags):
        if self._os is None and self._e is None:
            return
        nb = (name.encode()[:6] + b'\x00\x00\x00\x00\x00\x00')[:6]
        xi = int(x * 256) & 0xFFFF
        yi = int(y * 256) & 0xFFFF
        ai = int(angle * ANGLE_SCALE) & 0xFFFF
        pkt = struct.pack('<B6sHHHBB', PKT_POS, nb, xi, yi, ai,
                          min(255, max(0, int(health))), flags & 0xFF)
        self._send(pkt)

    def _send(self, pkt):
        try:
            if self._os is not None:
                self._os.send(pkt, BROADCAST_MAC, False)
            elif self._e is not None:
                self._e.send(BCAST, pkt, False)
        except Exception:
            pass

    def receive(self, my_name):
        if self._os is None and self._e is None:
            return 0
        damage = 0
        now = ticks_ms()

        if self._os is not None:
            msgs = self._inbox
            self._inbox = []
            for mac, data in msgs:
                damage += self._handle(mac, data, my_name, now)
        else:
            if ticks_diff(now, self._lock_t) >= RELOCK_INT:
                self._lock_channel()
                self._lock_t = now
            for _ in range(10):
                if not self._e.any():
                    break
                try:
                    mac, data = self._e.irecv(0)
                except Exception:
                    break
                if mac is None or data is None:
                    continue
                damage += self._handle(bytes(mac), data, my_name, now)

        expired = [k for k, v in self.peers.items()
                   if ticks_diff(now, v['time']) > PEER_TIMEOUT]
        for k in expired:
            del self.peers[k]

        return damage

    def _handle(self, mac, data, my_name, now):
        if data is None or len(data) < 2:
            return 0
        self.rx_count += 1
        pt = data[0]
        if pt == PKT_POS and len(data) >= 15:
            _, nb, xi, yi, ai, hp, fl = struct.unpack('<B6sHHHBB', data[:15])
            try:
                pname = nb.rstrip(b'\x00').decode('utf-8')
            except Exception:
                pname = 'anon'
            if mac == ZERO_MAC:
                return 0
            self.peers[mac] = {
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
                return dmg
        return 0

    def send_damage(self, target_name, dmg):
        if self._os is None and self._e is None:
            return
        tb = (target_name.encode()[:6] + b'\x00\x00\x00\x00\x00\x00')[:6]
        pkt = struct.pack('<B6sB', PKT_DMG, tb, min(255, dmg))
        self._send(pkt)

    def get_peers(self):
        return list(self.peers.values())

    def close(self):
        if self._e:
            try:
                self._e.active(False)
            except Exception:
                pass
