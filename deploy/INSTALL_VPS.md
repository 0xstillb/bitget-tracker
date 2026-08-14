# ติดตั้ง Private Core บน VPS

คู่มือนี้ใช้กับ **Ubuntu 24.04 LTS 64-bit** และติดตั้งแบบ systemd ซึ่งเป็น
วิธีแนะนำสำหรับ production. Core ต้องฟังเฉพาะ loopback หรือ IPv4 ของ
Tailscale เท่านั้น ห้ามเปิดพอร์ต 10000 ที่ public IP, router port-forward,
Cloudflare Tunnel หรือ public reverse proxy.

แหล่งโค้ดที่ใช้ deploy คือ branch `origin/integration` ของ
`0xstillb/bitget-tracker`. อย่า deploy จาก task branch และอย่าใส่ secret ลง
Git. คำสั่งที่มี `<COMMIT>` หรือ `<VPS_TAILSCALE_IP>` ต้องแทนค่าจริงก่อนรัน.

## 1. Preflight และ prerequisites

บันทึกสถานะเครื่องก่อนแก้ไข:

```sh
uname -a
lsb_release -a
df -h
free -h
ss -ltnp
systemctl --no-pager --full status tailscaled || true
```

ติดตั้ง runtime พื้นฐาน:

```sh
sudo apt update
sudo apt install -y ca-certificates curl git openssl python3 python3-venv
python3 --version
```

ต้องได้ Python 3.12 บน Ubuntu 24.04. ติดตั้ง Tailscale ตาม
[คู่มือ Linux อย่างเป็นทางการ](https://tailscale.com/docs/install/linux),
นำ VPS เข้า tailnet แล้วตรวจ IPv4:

```sh
sudo tailscale up
tailscale status
tailscale ip -4
```

นำ policy จาก `deploy/tailscale-acl.example.hujson` ไป merge ใน tailnet
policy และผูก VPS กับ `tag:bitget-core`. Policy อนุญาตเฉพาะ
`tag:bitget-viewer` เข้าถึง TCP 10000. อย่าลบ policy เดิมโดยไม่ review.

## 2. สร้าง service user และ persistent state

```sh
sudo useradd --system --home /var/lib/bitget-tracker --shell /usr/sbin/nologin bitget
sudo install -d -m 0755 -o root -g root /opt/bitget-tracker/releases
sudo install -d -m 0755 -o root -g root /etc/bitget-tracker
sudo install -m 0644 deploy/bitget-tracker-core.tmpfiles.example.conf /etc/tmpfiles.d/bitget-tracker-core.conf
sudo systemd-tmpfiles --create /etc/tmpfiles.d/bitget-tracker-core.conf
sudo install -d -m 0700 -o bitget -g bitget /var/lib/bitget-tracker/ms-playwright
```

ตรวจว่า `/var/lib/bitget-tracker` และไดเรกทอรี browser เป็นเจ้าของโดย
`bitget:bitget` และมี permission 0700.

## 3. ติดตั้ง release แบบ immutable

เลือก merge commit ที่ CI ผ่านจาก `origin/integration` แล้วแทน SHA นั้นใน
`<COMMIT>`:

```sh
sudo git clone --branch integration --single-branch https://github.com/0xstillb/bitget-tracker.git /opt/bitget-tracker/releases/<COMMIT>
sudo git -C /opt/bitget-tracker/releases/<COMMIT> checkout --detach <COMMIT>
cd /opt/bitget-tracker/releases/<COMMIT>
sudo git -C /opt/bitget-tracker/releases/<COMMIT> rev-parse HEAD
sudo git -C /opt/bitget-tracker/releases/<COMMIT> status --short
```

ผล `git status --short` ต้องว่าง และ SHA ต้องตรงกับ commit ที่ตั้งใจ deploy.
สร้าง virtual environment ภายใน release และติดตั้ง dependency จาก
`requirements.lock` พร้อมตรวจ hash:

หลังสลับ symlink แล้ว service จะใช้ interpreter ที่
`/opt/bitget-tracker/current/.venv/bin/python`.

```sh
sudo python3 -m venv /opt/bitget-tracker/releases/<COMMIT>/.venv
sudo /opt/bitget-tracker/releases/<COMMIT>/.venv/bin/python -m pip install --upgrade pip
sudo /opt/bitget-tracker/releases/<COMMIT>/.venv/bin/pip install --require-hashes -r /opt/bitget-tracker/releases/<COMMIT>/requirements.lock
sudo /opt/bitget-tracker/releases/<COMMIT>/.venv/bin/playwright install-deps chromium
sudo -u bitget env PLAYWRIGHT_BROWSERS_PATH=/var/lib/bitget-tracker/ms-playwright /opt/bitget-tracker/releases/<COMMIT>/.venv/bin/playwright install chromium
sudo ln -sfn /opt/bitget-tracker/releases/<COMMIT> /opt/bitget-tracker/current
```

คำสั่ง `install-deps` เปลี่ยนเฉพาะ system packages ที่ browser runtime ต้องใช้.
ตรวจรายการก่อนยืนยันบน VPS ที่มี workload อื่น. Node 22 จำเป็นเฉพาะเมื่อจะ
ทดลอง optional interactive login worker; Core ปกติและการ seed cookie แบบ
manual ไม่ต้องใช้ Node และควรคง `AUTO_LOGIN_ENABLED=false`.

## 4. สร้าง environment file

```sh
sudo install -m 0600 -o root -g root /opt/bitget-tracker/current/.env.example /etc/bitget-tracker/core.env
sudo chmod 600 /etc/bitget-tracker/core.env
sudoedit /etc/bitget-tracker/core.env
```

ตั้งค่าอย่างน้อย:

```dotenv
TRADERS=TraderName:YOUR_PORTFOLIO_ID
WRITE_TOKEN=GENERATE_A_UNIQUE_64_HEX_VALUE
INTERNAL_API_TOKEN=GENERATE_A_DIFFERENT_64_HEX_VALUE
CORE_BIND_HOST=<VPS_TAILSCALE_IP>
CORE_CORS_ORIGINS=http://<VPS_TAILSCALE_IP>:10000
PORT=10000
BITGET_COOKIE=
AUTO_LOGIN_ENABLED=false
```

สร้าง token คนละค่าด้วย `openssl rand -hex 32`; อย่า reuse ระหว่าง
`WRITE_TOKEN`, `INTERNAL_API_TOKEN` และ `COOKIE_SYNC_TOKEN`. ถ้าจะ seed cookie
ก่อน start ให้ใส่ `BITGET_COOKIE` ในไฟล์นี้ หรือเปิด dashboard ผ่าน tailnet
หลัง service ทำงานแล้ว. API key เป็น optional และต้องเป็น read-only เท่านั้น.

ตรวจโดยไม่พิมพ์ค่า secret ออกหน้าจอ:

```sh
sudo stat -c '%U:%G %a %n' /etc/bitget-tracker/core.env
sudo grep -E '^(CORE_BIND_HOST|PORT|AUTO_LOGIN_ENABLED)=' /etc/bitget-tracker/core.env
```

## 5. ติดตั้งและเริ่ม systemd service

```sh
sudo install -m 0644 /opt/bitget-tracker/current/deploy/bitget-tracker-core.service.example /etc/systemd/system/bitget-tracker-core.service
sudo systemctl daemon-reload
sudo systemctl enable --now bitget-tracker-core
sudo systemctl --no-pager --full status bitget-tracker-core
sudo journalctl -u bitget-tracker-core -n 100 --no-pager
```

## 6. ตรวจหลังติดตั้ง

บน VPS:

```sh
ss -ltnp | grep 10000
curl --fail --silent --show-error http://<VPS_TAILSCALE_IP>:10000/api/poller
```

พอร์ตต้อง bind ที่ `<VPS_TAILSCALE_IP>:10000` เท่านั้น ไม่ใช่ `0.0.0.0`,
public IP หรือ LAN IP. จาก Pi ทดสอบ read-only endpoint โดยใส่ token จริงใน
header (ระวัง shell history):

```sh
curl --fail --silent --show-error -H 'X-Internal-Token: <INTERNAL_API_TOKEN>' http://<VPS_TAILSCALE_IP>:10000/internal/v1/snapshot
```

ตอบ 200 เมื่อ token ถูกต้อง, 403 เมื่อขาด/ผิด และต้องไม่มี cookie, API secret,
passphrase หรือ raw browser state ใน response. ตรวจว่า restart count คงที่และ
ไฟล์ state ใน `/var/lib/bitget-tracker` เป็น mode 0600.

## 7. Upgrade

ทำซ้ำขั้นตอน clone, venv, locked dependencies และ browser install ใน release
ใหม่ก่อนสลับ symlink. จากนั้น:

```sh
sudo systemctl restart bitget-tracker-core
sudo systemctl --no-pager --full status bitget-tracker-core
sudo journalctl -u bitget-tracker-core -n 100 --no-pager
```

เก็บ release ก่อนหน้าอย่างน้อยหนึ่งชุด และอย่าลบ `/var/lib/bitget-tracker`.

## Rollback

หยุดเฉพาะ service นี้, ชี้ `current` กลับ release ก่อนหน้า แล้ว start ใหม่:

```sh
sudo systemctl stop bitget-tracker-core
sudo ln -sfn /opt/bitget-tracker/releases/<PREVIOUS_COMMIT> /opt/bitget-tracker/current
sudo systemctl start bitget-tracker-core
sudo systemctl --no-pager --full status bitget-tracker-core
```

อย่า restore state เก่าอัตโนมัติ. สำรอง `/var/lib/bitget-tracker` แบบเข้ารหัส
และตรวจ compatibility ก่อน restore. ดู checklist เพิ่มเติมใน `DEPLOYMENT.md`
และ `SECURITY_RELEASE_GATE.md`.
