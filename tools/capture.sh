#!/usr/bin/env bash
# Снять USB-трафик донгла, пока приложение в Wine что-то настраивает.
# Запускать в одном терминале, потом тыкать кнопки в SoundLink, потом Ctrl+C.
#
#   ./capture.sh            # ловим только наш девайс
#   ./capture.sh raw        # всё подряд в pcap: capture.pcap
#
set -euo pipefail

VID_PID="3142:00c3"
OUT="/tmp/fifine-usb-$(date +%H%M%S).pcap"

sudo modprobe usbmon 2>/dev/null || true

BUS=$(lsusb -d "$VID_PID" | sed -nE 's/^Bus ([0-9]+) Device.*/\1/p' | head -1)
if [[ -z "${BUS:-}" ]]; then
  echo "устройство $VID_PID не найдено" >&2
  exit 1
fi

IFACE="usbmon${BUS}"
echo "Шина $BUS → интерфейс $IFACE"
echo "Ловлю трафик. Переключай настройки в SoundLink. Ctrl+C — стоп."
echo "Пишу в $OUT"
echo

if [[ "${1:-}" == "raw" ]]; then
  sudo tshark -i "$IFACE" -w "$OUT"
else
  sudo tshark -i "$IFACE" -f "usb" -w "$OUT" 2>/dev/null
fi

echo
echo "Готово. Разбор:"
echo "  tshark -r $OUT -Y 'usb.transfer_type==0x21' -x     # SET_REPORT (запись в устройство)"
echo "  tshark -r $OUT -Y 'usb.transfer_type==0x81' -x     # interrupt IN (ответы)"
echo "  tshark -r $OUT -Y 'usb.data_len==64' -T fields -e usb.capdata"
