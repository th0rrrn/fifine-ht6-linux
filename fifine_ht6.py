#!/usr/bin/env python3
"""Прототип управления FIFINE HT6 с Linux (hidapi).

Протокол восстановлен из api_server.exe приложения SoundLink и проверен
на живом донгле.

    ./fifine_ht6.py devices      # какие HID-интерфейсы видит система
    ./fifine_ht6.py probe        # перебрать варианты отправки
    ./fifine_ht6.py state        # прочитать пакет состояния
    ./fifine_ht6.py mode 1       # sound_mode (0/1/2)
    ./fifine_ht6.py led off      # выключить подсветку (55 0C 00)
    ./fifine_ht6.py led rhythm   # always|cycle|breath|rhythm|on|off
    ./fifine_ht6.py color ff0000 # цвет подсветки (RRGGBB)
    ./fifine_ht6.py sleep 30     # таймер сна в минутах (255 = выключить)

Зависимости: python-hidapi
"""
import sys
import time

try:
    import hid
except ImportError:
    sys.exit("нужен python-hidapi: sudo pacman -S python-hidapi")

VID, PID = 0x3142, 0x00C3
REPORT = 64

CMD_GET_STATE = [0x55, 0x65, 0x01, 0x00]
CMD_SET_SOUND_MODE = [0x55, 0x21, 0x01]   # + [mode]
CMD_SET_SLEEP = [0x55, 0x23, 0x01]        # + [minutes], 255 = выкл
CMD_GET_LED = [0x55, 0x06, 0x00]          # ответ: 55 06 mode RR GG BB speed ..
CMD_LED_ENABLE = [0x55, 0x0C, 0x01]       # включить RGB
CMD_LED_DISABLE = [0x55, 0x0C, 0x00]      # выключить RGB (настоящий off)

# режим подсветки -> (mode, число цветов в таблице)
# снято с живого трафика и из вендорского приложения
LED_MODES = {
    "always": (0x00, 8),
    "cycle":  (0x01, 126),
    "breath": (0x02, 128),
    "rhythm": (0x03, 128),
}

# индексы в пакете состояния (из HidMonitor._parse_packet)
STATE_FIELDS = {
    2: "battery_level",
    3: "battery_status",
    4: "sound_mode",
    5: "surround_71",
    6: "spatial_sound",
    7: "sleep_time",
    8: "sidetone_on",
    9: "sidetone_vol",
    12: "dongle_ver_major",
    13: "dongle_ver_minor",
    16: "headset_ver_major",
    17: "headset_ver_minor",
    18: "feature_rgb",
    19: "feature_dongle_rgb",
    20: "feature_rgb_switch",
    21: "feature_dongle_rgb_switch",
}
STATUS_OFF = 0x0A
STATUS_BLE_LOST = 0x1A


# ---------- низкий уровень ----------

def enumerate_devices():
    return hid.enumerate(VID, PID)


def open_device(interface=None, usage_page=None):
    """Открыть HID-устройство. Без аргументов — первое доступное."""
    for d in enumerate_devices():
        if interface is not None and d.get("interface_number") != interface:
            continue
        if usage_page is not None and d.get("usage_page") != usage_page:
            continue
        try:
            dev = hid.device()
            dev.open_path(d["path"])
            dev.set_nonblocking(1)
            return dev
        except Exception:
            continue
    return None


def pad(payload):
    return bytes(payload) + b"\x00" * (REPORT - len(payload))


def send(dev, payload, mode="raw"):
    """Отправить пакет.

    По дескриптору (usage page 0xFF90) первый байт — HID Report ID 0x55,
    далее 63 байта нагрузки. hidapi сам трактует data[0] как report id.
    """
    data = pad(payload)
    if mode == "prefix0":
        return dev.write(b"\x00" + data)
    if mode == "feature":
        return dev.send_feature_report(data)
    return dev.write(data)


def read_packet(dev, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = dev.read(REPORT, 200)
        if data:
            return bytes(data)
    return None


def parse_state(pkt):
    if len(pkt) < 2 or pkt[0] != 0x55:
        return None
    if pkt[1] == STATUS_OFF:
        return {"connected": False, "reason": "наушники выключены или отключены"}
    if len(pkt) >= 4 and pkt[3] == STATUS_BLE_LOST:
        return {"connected": False, "reason": "потеряна связь с гарнитурой (BLE)"}
    out = {"connected": True}
    for idx, name in STATE_FIELDS.items():
        if idx < len(pkt):
            out[name] = pkt[idx]
    return out


def get_state(dev, mode="raw"):
    send(dev, CMD_GET_STATE, mode)
    pkt = read_packet(dev)
    if pkt is None:
        return None, None
    return parse_state(pkt), pkt


def get_led(dev):
    send(dev, CMD_GET_LED)
    pkt = read_packet(dev, 1.0)
    if pkt and len(pkt) >= 6 and pkt[0] == 0x55 and pkt[1] == 0x06:
        return pkt[3], pkt[4], pkt[5]
    return None


# ---------- высокий уровень ----------

def _apply_led(dev, mode, count, r, g, b):
    """Полная последовательность LED-движка из вендорского приложения.

        55 0C 01                    включить RGB
        55 02 00                    остановить движок
        55 03 mode count 00 0A 00   режим и число цветов в таблице
        55 04 <index> <4×RGB>       таблица цветов
        55 05 00                    сохранить во флеш
        55 01 00                    запустить движок

    Без этой последовательности донгл молча выбрасывает запись, а чтение
    ``55 06`` продолжает отдавать старое значение.
    """
    send(dev, CMD_LED_ENABLE)
    time.sleep(0.01)
    send(dev, [0x55, 0x02, 0x00])
    time.sleep(0.01)
    send(dev, [0x55, 0x03, mode, count & 0xFF, (count >> 8) & 0xFF, 0x0A, 0x00])
    time.sleep(0.01)
    upload_color_table(dev, r, g, b, count)
    send(dev, [0x55, 0x05, 0x00])
    time.sleep(0.01)
    send(dev, [0x55, 0x01, 0x00])


def upload_color_table(dev, r, g, b, count):
    """Залить таблицу цветов.

    Для breath/rhythm — плавный переход от выбранного цвета к чёрному
    (128 значений). Для always используется только первая запись. Для
    cycle вендорское приложение заливает отдельную фиксированную радугу;
    здесь используется тот же плавный переход.
    """
    for base in range(0, count, 4):
        payload = [0x55, 0x04, base & 0xFF, (base >> 8) & 0xFF]
        for i in range(4):
            if base + i < count:
                k = 1.0 - (base + i) / 128
                payload += [int(r * k), int(g * k), int(b * k)]
            else:
                payload += [0, 0, 0]
        send(dev, payload)
        time.sleep(0.01)


def set_led_mode(dev, name):
    if name not in LED_MODES:
        raise ValueError(name)
    mode, count = LED_MODES[name]
    led = get_led(dev)
    r, g, b = led if led else (0xFF, 0xFF, 0xFF)
    _apply_led(dev, mode, count, r, g, b)


def set_led_off(dev):
    """Штатное выключение подсветки наушников (55 0C 00)."""
    send(dev, CMD_LED_DISABLE)


def set_led_on(dev):
    """Включить подсветку обратно (55 0C 01)."""
    send(dev, CMD_LED_ENABLE)


def set_color(dev, r, g, b, mode_name="always"):
    mode, count = LED_MODES.get(mode_name, LED_MODES["always"])
    _apply_led(dev, mode, count, r, g, b)


# ---------- CLI ----------

def cmd_devices():
    devs = enumerate_devices()
    if not devs:
        print("устройство 3142:00c3 не найдено")
        return
    for i, d in enumerate(devs):
        print(f"[{i}] interface={d.get('interface_number')} "
              f"usage_page=0x{d.get('usage_page', 0):04X} "
              f"path={d.get('path')} product={d.get('product_string')!r}")


def cmd_probe():
    dev = open_device()
    if not dev:
        sys.exit("не удалось открыть устройство")
    for mode in ("raw", "prefix0", "feature"):
        try:
            send(dev, CMD_GET_STATE, mode)
            pkt = read_packet(dev, 1.5)
        except Exception as e:
            print(f"{mode:8s}: ошибка {e}")
            continue
        print(f"{mode:8s}: {pkt.hex(' ') if pkt else 'ответа нет'}")
        time.sleep(0.3)
    dev.close()


def cmd_state():
    dev = open_device()
    if not dev:
        sys.exit("не удалось открыть устройство")
    state, pkt = get_state(dev)
    if pkt:
        print("сырой пакет:", pkt.hex(" "))
    if state is None:
        print("ответа нет")
    else:
        for k, v in state.items():
            print(f"  {k:26s} {v}")
        led = get_led(dev)
        if led:
            print(f"  {'led_color':26s} #{led[0]:02x}{led[1]:02x}{led[2]:02x}")
    dev.close()


def cmd_mode(value):
    dev = open_device()
    if not dev:
        sys.exit("не удалось открыть устройство")
    send(dev, CMD_SET_SOUND_MODE + [int(value)])
    time.sleep(0.5)
    state, _ = get_state(dev)
    if state:
        print(f"sound_mode = {state.get('sound_mode')}")
    dev.close()


def cmd_led(name):
    if name not in LED_MODES and name not in ("on", "off"):
        print("режимы:", ", ".join(list(LED_MODES) + ["on", "off"]))
        return
    dev = open_device()
    if not dev:
        sys.exit("не удалось открыть устройство")
    if name == "off":
        set_led_off(dev)
    elif name == "on":
        set_led_on(dev)
    else:
        set_led_mode(dev, name)
    print(f"подсветка: {name}")
    dev.close()


def cmd_color(hexcolor, mode_name="always"):
    h = hexcolor.lstrip("#")
    if len(h) != 6:
        sys.exit("цвет задаётся как RRGGBB, например ff0000")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    dev = open_device()
    if not dev:
        sys.exit("не удалось открыть устройство")
    set_color(dev, r, g, b, mode_name)
    time.sleep(0.4)
    led = get_led(dev)
    if led:
        print(f"цвет: #{led[0]:02x}{led[1]:02x}{led[2]:02x}")
    else:
        print("команда отправлена, подтверждения нет")
    dev.close()


def cmd_sleep(minutes):
    dev = open_device()
    if not dev:
        sys.exit("не удалось открыть устройство")
    send(dev, CMD_SET_SLEEP + [int(minutes)])
    print(f"таймер сна: {minutes} (255 = выкл)")
    dev.close()


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    cmd = args[0]
    if cmd == "devices":
        cmd_devices()
    elif cmd == "probe":
        cmd_probe()
    elif cmd == "state":
        cmd_state()
    elif cmd == "mode" and len(args) > 1:
        cmd_mode(args[1])
    elif cmd == "led" and len(args) > 1:
        cmd_led(args[1])
    elif cmd == "color" and len(args) > 1:
        cmd_color(args[1], args[2] if len(args) > 2 else "always")
    elif cmd == "sleep" and len(args) > 1:
        cmd_sleep(args[1])
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
