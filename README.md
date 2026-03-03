# Print Tracker (Makerspace Kiosk MVP)

A Flask kiosk service for tracking 3D prints in a shared makerspace:

- Patrons register prints at a kiosk before starting.
- A label with a unique print ID and QR code is generated/printed.
- Staff scan or enter the ID to mark prints `finished` or `failed`.
- Completion/failure emails are sent to users.
- Monthly reports and CSV exports summarize print activity.

The data model is intentionally flat to support easy CSV export and future migration to a Google Sheets backend.

## 1) Quick Local Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
flask --app run.py init-db
python run.py
```

Open:

- Kiosk: `http://localhost:5000/kiosk/register`
- Staff: `http://localhost:5000/staff/`
- Reports: `http://localhost:5000/reports/monthly`

Staff page password is `staffpw` by default (`STAFF_PASSWORD` in `.env`).

If port `5000` is already in use:

```bash
PORT=5050 python run.py
```

## 2) Raspberry Pi Deployment (Beginner Friendly)

If this is your first Linux setup, use the deployment script. It automates package install, Python setup, `.env`, database initialization, CUPS service enablement, and systemd service setup.

### 2.1) One-time setup (copy/paste)

Use a fresh Raspberry Pi OS install (Desktop recommended), then open Terminal and run:

Replace `<YOUR_REPO_URL>` in the command block first.

```bash
sudo apt update
sudo apt install -y git

sudo mkdir -p /opt/print-tracker
sudo chown -R "$USER:$USER" /opt/print-tracker
cd /opt/print-tracker

git clone <YOUR_REPO_URL> .
chmod +x scripts/deploy_rpi.sh
./scripts/deploy_rpi.sh
```

What the script asks for:

1. Service user/group (usually keep defaults).
2. Port (usually keep `5000`).
3. Print mode (`cups` for real printer, `mock` for testing).
4. CUPS queue name (example: `QL800`).
5. CUPS media token (default: `DK-1202`).

The script also copies the bundled Makerspace logo to `assets/makerspace-logo.png` for label branding.
Staff password defaults to `staffpw` unless you set `STAFF_PASSWORD` in `.env`.
After first boot, change `STAFF_PASSWORD` to a real value and restart the service.

### 2.2) Brother QL-800 printer setup (manual part)

The one thing you still do manually is add the printer queue in CUPS.

1. Plug in the Brother QL-800 over USB.
2. Open CUPS in a browser on the Pi: `http://localhost:631`.
3. Go to `Administration` -> `Add Printer`.
4. Select the QL-800 USB device.
5. Choose the QL-800 driver/model (installed by `printer-driver-ptouch`).
6. Set queue name (example: `QL800`).

Then verify in Terminal:

```bash
lpstat -e
lpstat -p -d
lpoptions -p <QUEUE_NAME> -l | grep -Ei 'media|PageSize'
lp -d <QUEUE_NAME> /usr/share/cups/data/testprint
```

If you changed queue/media values after running the script, edit `.env` and restart:

```bash
sudo systemctl restart print-tracker
```

### 2.3) Confirm it works

Open these pages from the Pi (or another device on the same network):

- `http://<PI_HOSTNAME_OR_IP>:5000/kiosk/register`
- `http://<PI_HOSTNAME_OR_IP>:5000/staff/`
- `http://<PI_HOSTNAME_OR_IP>:5000/reports/monthly`

Run one full workflow test:

1. Create a print on kiosk page.
2. Confirm a physical label prints.
3. Scan QR on a staff device, sign in if prompted, then mark complete/failed.
4. Confirm email behavior.
5. Confirm record appears in monthly CSV.

### 2.4) Re-run deployment script later

Use this after updates or config changes:

```bash
cd /opt/print-tracker
git pull
./scripts/deploy_rpi.sh --non-interactive
```

Useful script options:

```bash
./scripts/deploy_rpi.sh --help
```

Common examples:

```bash
./scripts/deploy_rpi.sh --non-interactive --printer-queue QL800 --media DK-1202
./scripts/deploy_rpi.sh --print-mode mock
```

### 2.5) Google OAuth setup (Gmail + Google Sheets)

Use this when you want:

- completion emails sent from a Google account via Gmail API.
- every job upserted into a Google Sheet.

1. In Google Cloud Console:
   - create/select a project.
   - enable `Gmail API` and `Google Sheets API`.
   - configure OAuth consent screen.
   - create OAuth Client ID (`Desktop app`) and download JSON.
2. Sign into the generic makerspace Google account in your browser.
3. Run the helper script:

```bash
cd /opt/print-tracker
source .venv/bin/activate
python scripts/google_oauth_bootstrap.py \
  --client-secrets /path/to/client_secret.json \
  --gmail-sender makerspace@example.com
```

4. Copy printed values into `/opt/print-tracker/.env`.
5. Set your spreadsheet:
   - create/open a Google Sheet.
   - copy the spreadsheet ID from the URL.
   - put it in `GOOGLE_SHEETS_SPREADSHEET_ID`.
6. Restart service:

```bash
sudo systemctl restart print-tracker
```

7. Submit one test job and confirm:
   - job row appears in the configured worksheet.
   - completion email is sent through the Google account.

### 2.6) Staff mobile scanning on Pi access-point network

Yes, this works. If the Pi is an access point, staff iPads/phones can join that Wi-Fi and scan/update prints.

Required setup:

1. Configure AP SSID/password on Pi (staff-only credentials).
2. Set `KIOSK_BASE_URL` to the Pi AP address (example `http://192.168.4.1:5000`).
3. On staff page, set QR mode to `Open staff page link`.
4. Staff logs into `/staff` once on the iPad browser, then scans labels.

Security behavior:

- QR links always route to staff endpoints.
- Staff login is required before a print can be marked complete/failed.
- Patrons can scan labels, but cannot update status unless they know the staff password.
- Staff mobile users must authenticate at `/staff/login` before updates are allowed.

## 3) Kiosk / Touchscreen Notes

- The kiosk form is optimized for 7" touch displays.
- Portrait mode layout targets Pi Display 2 (`720x1280`) and keeps a fixed shell to reduce keyboard-triggered reflow.
- On short viewports (for example with on-screen keyboard open), layout reduces vertical waste.
- Enable on-screen keyboard in Raspberry Pi OS accessibility settings for touch-only interaction.
- Most USB QR scanners work as keyboard wedge devices and require no extra app-side configuration.

## 4) Core Workflow

1. User fills in kiosk form:
   - First name, last name, NCSU email local part, file name, project type.
   - Academic: course number + instructor.
   - Research: department + PI.
2. App creates unique print ID (`PT-YYYYMMDD-HHMMSS-##`) with `in_progress` status.
3. Label image is generated and sent to CUPS (or kept as file in mock mode).
4. Staff scan ID/QR and mark finished or failed.
5. Completion email template is sent.
6. Reports and CSV summarize activity monthly.

## 5) Configuration Reference

Important `.env` keys:

- `DATABASE_URL`: SQLite URL (absolute path recommended on Pi).
- `STAFF_PASSWORD`: password for `/staff` access (default `staffpw`).
- `LABEL_PRINT_MODE`: `mock` or `cups`.
- `KIOSK_BASE_URL`: base URL encoded in QR links for staff mobile scans (example `http://192.168.4.1:5000`).
- `LABEL_PRINTER_QUEUE`: CUPS queue name.
- `LABEL_OUTPUT_DIR`: where generated label images are stored.
- `LABEL_STOCK`: `DK1202` for Brother QL-800 DK-1202 labels.
- `LABEL_DPI`: `300` recommended.
- `LABEL_ORIENTATION`: `landscape` (default) or `portrait`.
- `LABEL_QR_PAYLOAD_MODE`: `url` recommended for iPad/phone camera scanning, `id` for USB scanner workflows.
- `LABEL_QR_SIZE_INCH`: QR size on label (default `0.5`).
- `LABEL_CUPS_MEDIA`: CUPS media token (`DK-1202` or your driver's exact token).
- `LABEL_CUPS_EXTRA_OPTIONS`: additional comma-separated CUPS options.
- `LABEL_SAVE_LABEL_FILES`: base default (`true`). Staff can toggle this live on the staff page.
- `LABEL_BRAND_TEXT`: fallback header text if no logo path.
- `LABEL_BRAND_LOGO_PATH`: local logo file path (PNG recommended).
- `DEFAULT_PRINTER_NAME`: stored printer descriptor.
- `SMTP_*`: SMTP host/port/user/pass/TLS/from for completion emails.
- `EMAIL_PROVIDER`: `smtp`, `gmail_api`, or `auto`.
- `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` / `GOOGLE_OAUTH_REFRESH_TOKEN`: OAuth credentials used by Gmail and Sheets APIs.
- `GOOGLE_OAUTH_TOKEN_URI`: token endpoint (default `https://oauth2.googleapis.com/token`).
- `GOOGLE_GMAIL_SENDER`: optional `From:` override for Gmail API sends.
- `GOOGLE_SHEETS_SYNC_ENABLED`: `true` to enable sync.
- `GOOGLE_SHEETS_SPREADSHEET_ID`: target spreadsheet ID.
- `GOOGLE_SHEETS_WORKSHEET`: worksheet tab name (default `PrintJobs`).

Staff page operational controls:

- completion email on/off
- label image save on/off
- label retention days (1-30; set to `1` to keep only today's labels)
- QR mode switch (`link` for mobile camera, `ID` for scanner wedge)
- reprint button for active and recently completed jobs

## 6) Reports and CSV Columns

Monthly CSV export includes flat columns designed for spreadsheet workflows:

- `PrintID`
- `CreatedAt`
- `CompletedAt`
- `Status`
- `ProjectType`
- `FileName`
- `UserName`
- `UserEmail`
- `CourseNumber`
- `Instructor`
- `Department`
- `PI`
- `CompletedBy`

## 7) Email Templates

Edit these files to match your makerspace messaging:

- `print_tracker/templates/email_success.txt`
- `print_tracker/templates/email_failure.txt`

## 8) Troubleshooting

- `Port 5000 already in use`:
  - Run with `PORT=5050` or stop conflicting service.
- `sqlite3.OperationalError: unable to open database file`:
  - Use absolute `DATABASE_URL` in `.env`.
  - Ensure parent directory exists and service user can write to it.
- Label preview 404 / missing PNG:
  - If label saving is turned off in staff settings, preview PNGs are not stored by design.
  - If you enable `LABEL_SAVE_LABEL_FILES=true`, ensure `LABEL_OUTPUT_DIR` is writable and consistent in `.env`.
  - Restart service after changing `.env`.
- Can't access `/staff`:
  - Use the staff password from `.env` (`STAFF_PASSWORD`, default `staffpw`).
- Logo not showing:
  - Verify `LABEL_BRAND_LOGO_PATH` exists and is readable.
  - Restart service after `.env` changes.
- Service does not start:
  - Check status: `sudo systemctl status print-tracker --no-pager`
  - Check logs: `journalctl -u print-tracker -f`
- Need to safely re-run setup:
  - `cd /opt/print-tracker && ./scripts/deploy_rpi.sh --non-interactive`
- iPad/phone scan opens unreachable URL:
  - Set `KIOSK_BASE_URL` to a Pi-reachable address on your network (for AP mode, usually `http://192.168.4.1:5000`).
  - In staff settings, use QR mode `Open staff page link`.
- Google OAuth refresh token missing/expired:
  - Re-run `python scripts/google_oauth_bootstrap.py --client-secrets ...`
  - Update `.env` and restart service.
- Google Sheet sync fails:
  - Confirm `GOOGLE_SHEETS_SPREADSHEET_ID` is correct.
  - Confirm the OAuth account has edit access to the spreadsheet.
