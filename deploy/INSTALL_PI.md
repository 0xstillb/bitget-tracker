# ติดตั้ง read-only Viewer บน Raspberry Pi

คู่มือนี้ใช้กับ Raspberry Pi ที่รัน **Raspberry Pi OS Bookworm 64-bit**.
โหมดมาตรฐานคือ Pi Viewer เรียก Private Core ผ่าน Tailscale. ถ้าต้องการให้ Pi
เป็นเจ้าของ Core และ auto-login ด้วย app approval ให้ใช้คู่มือ
`deploy/PI_AUTO_LOGIN.md` เพิ่มเติม.

ใช้โค้ดจาก branch `origin/integration` ของ `0xstillb/bitget-tracker` เท่านั้น.
คำสั่งที่มี `<COMMIT>`, `<VPS_TAILSCALE_IP>` หรือ `<PI_LAN_IP>` ต้องแทนค่าจริง.

## 1. Coexistence preflight

ถ้าเครื่องนี้มี Grimmory, moOde หรือ audio services อยู่แล้ว ให้บันทึกสถานะ
ก่อนแก้ไขและห้าม stop/disable/rename service, user, port หรือไฟล์ของระบบเหล่านั้น:

```sh
uname -a
cat /etc/os-release
systemctl --no-pager --full --type=service --state=running
ss -ltnp
df -h
free -h
```

ถ้า TCP 8080 ถูกใช้ ให้เลือก port ว่างและเปลี่ยนเฉพาะ `PI_VIEWER_PORT`, URL
ของ ESP32 และ loopback origin ของ cloudflared. อย่าเปลี่ยน port ของ Grimmory,
moOde, SSH หรือ audio service เพื่อหลีกทางให้ Viewer.

## 2. ติดตั้ง prerequisites และ Tailscale

Viewer ใช้ Python standard library จึงไม่ต้องติดตั้ง Python packages เพิ่ม:

```sh
sudo apt update
sudo apt install -y ca-certificates curl git python3
python3 --version
```

ติดตั้ง Tailscale ตาม
[คู่มือ Linux อย่างเป็นทางการ](https://tailscale.com/docs/install/linux),
นำ Pi เข้า tailnet และผูก `tag:bitget-viewer`:

```sh
sudo tailscale up
tailscale status
tailscale ip -4
```

ใช้ policy จาก `deploy/tailscale-acl.example.hujson`; policy ต้องให้ Viewer
เข้าถึงเฉพาะ Core ที่ TCP 10000. ทดสอบจาก Pi ว่าเข้าถึง
`http://<VPS_TAILSCALE_IP>:10000` ได้ แต่ public network เข้า Core ไม่ได้.

## 3. สร้าง user, cache และ release

```sh
sudo useradd --system --home /var/lib/bitget-pi-viewer --shell /usr/sbin/nologin bitget-viewer
sudo install -d -m 0755 -o root -g root /opt/bitget-tracker/releases
sudo install -d -m 0755 -o root -g root /etc/bitget-pi-viewer
sudo git clone --branch integration --single-branch https://github.com/0xstillb/bitget-tracker.git /opt/bitget-tracker/releases/<COMMIT>
sudo git -C /opt/bitget-tracker/releases/<COMMIT> checkout --detach <COMMIT>
cd /opt/bitget-tracker/releases/<COMMIT>
sudo git -C /opt/bitget-tracker/releases/<COMMIT> rev-parse HEAD
sudo git -C /opt/bitget-tracker/releases/<COMMIT> status --short
sudo ln -sfn /opt/bitget-tracker/releases/<COMMIT> /opt/bitget-tracker/current
sudo install -m 0644 deploy/bitget-pi-viewer.tmpfiles.example.conf /etc/tmpfiles.d/bitget-pi-viewer.conf
sudo systemd-tmpfiles --create /etc/tmpfiles.d/bitget-pi-viewer.conf
```

SHA ต้องตรงกับ merge commit ที่ CI ผ่านบน `origin/integration`, worktree ต้อง
สะอาด และ `/var/lib/bitget-pi-viewer` ต้องเป็น `bitget-viewer:bitget-viewer`
mode 0700.

## 4. ตั้งค่า Viewer

```sh
sudo install -m 0600 -o root -g root /opt/bitget-tracker/current/deploy/pi-viewer.env.example /etc/bitget-pi-viewer/viewer.env
sudo chmod 600 /etc/bitget-pi-viewer/viewer.env
sudoedit /etc/bitget-pi-viewer/viewer.env
```

ตั้งค่า:

```dotenv
CORE_SNAPSHOT_URL=http://<VPS_TAILSCALE_IP>:10000/internal/v1/snapshot
INTERNAL_API_TOKEN=SAME_VALUE_AS_VPS_INTERNAL_API_TOKEN
CORE_SNAPSHOT_TIMEOUT_SEC=5
PI_VIEWER_BIND_HOST=0.0.0.0
PI_VIEWER_PORT=8080
PI_VIEWER_CACHE_PATH=/var/lib/bitget-pi-viewer/viewer-cache.json
```

Pi Viewer ต้องมีเฉพาะ `INTERNAL_API_TOKEN` ในโหมดมาตรฐาน; ห้ามใส่ `WRITE_TOKEN`,
Bitget cookie, password, API secret หรือ passphrase ใน Viewer env. ถ้าใช้
Pi Core auto-login ให้แยก Core env ตาม `PI_AUTO_LOGIN.md`. `0.0.0.0` ใช้เพื่อให้
ESP32 ใน trusted LAN เข้า Viewer ได้—ต้องไม่ทำ router port-forward มาที่ port นี้.

## 5. ติดตั้งและเริ่ม systemd service

```sh
sudo install -m 0644 /opt/bitget-tracker/current/deploy/bitget-pi-viewer.service.example /etc/systemd/system/bitget-pi-viewer.service
sudo systemctl daemon-reload
sudo systemctl enable --now bitget-pi-viewer
sudo systemctl --no-pager --full status bitget-pi-viewer
sudo journalctl -u bitget-pi-viewer -n 100 --no-pager
```

## 6. ตรวจ Viewer และ ESP32

บน Pi:

```sh
curl --fail --silent --show-error http://127.0.0.1:8080/api/v1/health
curl --fail --silent --show-error http://127.0.0.1:8080/api/v1/summary
curl --fail --silent --show-error http://127.0.0.1:8080/api/esp32
ss -ltnp | grep 8080
```

จากเครื่องใน LAN เปิด `http://<PI_LAN_IP>:8080/`. ตั้ง base URL ใน firmware
เป็น `http://<PI_LAN_IP>:8080`; ESP32 ใช้ `/api/esp32`,
`/api/esp32/positions` และ `/api/esp32/history`. เมื่อหยุด Core ชั่วคราว
Viewer ต้องยังส่ง last-good cache และ `/api/v1/health` ต้องระบุ `stale=true`.

ก่อนตั้ง firewall ให้ตรวจ SSH และทุก port ของ Grimmory/moOde ก่อน. อย่าเปิด
UFW แบบ copy/paste หากยังไม่มี allow rule สำหรับ SSH และบริการเดิม. ตัวอย่าง
policy LAN-only อยู่ใน `CLOUDFLARE_VIEWER.md`.

ถ้าต้องการใช้งานผ่านมือถือจากภายนอก ให้ทำตาม `CLOUDFLARE_VIEWER.md` และ expose
เฉพาะ Viewer ผ่าน Cloudflare Access. ตรวจ config ด้วย
`cloudflared tunnel ingress rule`; ห้ามเพิ่ม Core port 10000 เป็น ingress.

## 7. Upgrade

clone merge commit ใหม่เป็น release directory ใหม่, ยืนยัน SHA/worktree แล้ว
สลับ symlink และ restart เฉพาะ Viewer:

```sh
sudo ln -sfn /opt/bitget-tracker/releases/<COMMIT> /opt/bitget-tracker/current
sudo systemctl restart bitget-pi-viewer
sudo systemctl --no-pager --full status bitget-pi-viewer
```

ตรวจหน้า Viewer, stale recovery, ESP32, Grimmory, moOde และ audio playback
หลัง upgrade ทุกครั้ง.

## Rollback

```sh
sudo systemctl stop bitget-pi-viewer
sudo ln -sfn /opt/bitget-tracker/releases/<PREVIOUS_COMMIT> /opt/bitget-tracker/current
sudo systemctl start bitget-pi-viewer
sudo systemctl --no-pager --full status bitget-pi-viewer
```

อย่าลบหรือ restore `/var/lib/bitget-pi-viewer` อัตโนมัติ. เก็บ release ก่อนหน้า
อย่างน้อยหนึ่งชุด และยืนยันว่าบริการ Grimmory/moOde/audio ไม่เปลี่ยนจาก
preflight.
