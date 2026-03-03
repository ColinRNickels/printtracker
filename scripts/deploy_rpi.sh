#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

SERVICE_NAME="print-tracker"
SERVICE_USER="${SUDO_USER:-${USER}}"
SERVICE_GROUP="$(id -gn "${SERVICE_USER}" 2>/dev/null || echo "${SERVICE_USER}")"
PORT="5000"
PRINT_MODE="cups"
PRINTER_QUEUE="QL800"
LABEL_MEDIA="DK-1202"
LOGO_SOURCE=""
NON_INTERACTIVE=0
SKIP_APT=0
SKIP_SERVICE=0
SKIP_CUPS=0
SKIP_DB_INIT=0

usage() {
  cat <<'EOF'
Usage: ./scripts/deploy_rpi.sh [options]

Automates Raspberry Pi deployment for Print Tracker.
Run from the project root after cloning the repository.

Options:
  --non-interactive        Use defaults and skip prompts.
  --service-user USER      Linux user that runs the app service.
  --service-group GROUP    Linux group that runs the app service.
  --port PORT              App port (default: 5000).
  --print-mode MODE        "cups" or "mock" (default: cups).
  --printer-queue NAME     CUPS queue name (default: QL800).
  --media NAME             CUPS media token (default: DK-1202).
  --logo-source PATH       Optional local PNG path for label logo.
  --skip-apt               Skip apt package install/update.
  --skip-cups              Skip CUPS service setup and printer checks.
  --skip-service           Skip systemd service setup.
  --skip-db-init           Skip database initialization.
  -h, --help               Show this help.
EOF
}

log() {
  printf '\n[deploy] %s\n' "$*"
}

warn() {
  printf '\n[deploy] WARNING: %s\n' "$*" >&2
}

die() {
  printf '\n[deploy] ERROR: %s\n' "$*" >&2
  exit 1
}

run_root() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

prompt_default() {
  local prompt="$1"
  local default="$2"
  local input=""
  if [[ "${NON_INTERACTIVE}" -eq 1 ]]; then
    printf '%s' "${default}"
    return 0
  fi
  read -r -p "${prompt} [${default}]: " input
  if [[ -n "${input}" ]]; then
    printf '%s' "${input}"
  else
    printf '%s' "${default}"
  fi
}

set_env_value() {
  local env_file="$1"
  local key="$2"
  local value="$3"
  python3 - "${env_file}" "${key}" "${value}" <<'PY'
from pathlib import Path
import sys

env_path = Path(sys.argv[1])
key = sys.argv[2]
value = sys.argv[3]

if env_path.exists():
    lines = env_path.read_text().splitlines()
else:
    lines = []

needle = f"{key}="
updated = []
found = False
for line in lines:
    if line.startswith(needle):
        updated.append(f"{key}={value}")
        found = True
    else:
        updated.append(line)

if not found:
    updated.append(f"{key}={value}")

env_path.write_text("\n".join(updated).rstrip() + "\n")
PY
}

get_env_value() {
  local env_file="$1"
  local key="$2"
  python3 - "${env_file}" "${key}" <<'PY'
from pathlib import Path
import sys

env_path = Path(sys.argv[1])
key = sys.argv[2]
needle = f"{key}="

if not env_path.exists():
    sys.exit(0)

for line in env_path.read_text().splitlines():
    if line.startswith(needle):
        print(line[len(needle):])
        break
PY
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --non-interactive)
      NON_INTERACTIVE=1
      shift
      ;;
    --service-user)
      SERVICE_USER="$2"
      shift 2
      ;;
    --service-group)
      SERVICE_GROUP="$2"
      shift 2
      ;;
    --port)
      PORT="$2"
      shift 2
      ;;
    --print-mode)
      PRINT_MODE="$2"
      shift 2
      ;;
    --printer-queue)
      PRINTER_QUEUE="$2"
      shift 2
      ;;
    --media)
      LABEL_MEDIA="$2"
      shift 2
      ;;
    --logo-source)
      LOGO_SOURCE="$2"
      shift 2
      ;;
    --skip-apt)
      SKIP_APT=1
      shift
      ;;
    --skip-cups)
      SKIP_CUPS=1
      shift
      ;;
    --skip-service)
      SKIP_SERVICE=1
      shift
      ;;
    --skip-db-init)
      SKIP_DB_INIT=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "Unknown option: $1"
      ;;
  esac
done

[[ -f "${PROJECT_DIR}/requirements.txt" ]] || die "Run this script from inside the project repository."
[[ "${PRINT_MODE}" == "cups" || "${PRINT_MODE}" == "mock" ]] || die "--print-mode must be cups or mock."

if [[ "${NON_INTERACTIVE}" -eq 0 ]]; then
  log "Interactive setup. Press Enter to accept defaults."
  SERVICE_USER="$(prompt_default "Service user" "${SERVICE_USER}")"
  SERVICE_GROUP="$(prompt_default "Service group" "${SERVICE_GROUP}")"
  PORT="$(prompt_default "Web app port" "${PORT}")"
  PRINT_MODE="$(prompt_default "Print mode (cups or mock)" "${PRINT_MODE}")"
  PRINTER_QUEUE="$(prompt_default "CUPS queue name" "${PRINTER_QUEUE}")"
  LABEL_MEDIA="$(prompt_default "CUPS media token" "${LABEL_MEDIA}")"
fi

[[ "${PRINT_MODE}" == "cups" || "${PRINT_MODE}" == "mock" ]] || die "Print mode must be cups or mock."
[[ "${PORT}" =~ ^[0-9]+$ ]] || die "Port must be a number."

APP_DIR="${PROJECT_DIR}"
INSTANCE_DIR="${APP_DIR}/instance"
LABEL_DIR="${APP_DIR}/labels"
ASSETS_DIR="${APP_DIR}/assets"
LOGO_DEST="${ASSETS_DIR}/makerspace-logo.png"
ENV_FILE="${APP_DIR}/.env"
VENV_DIR="${APP_DIR}/.venv"
DEFAULT_LOGO_SOURCE="${APP_DIR}/print_tracker/static/ncsu-makerspace-logo-long-v2.png"

if [[ "${APP_DIR}" == *" "* ]]; then
  warn "Project directory contains spaces: ${APP_DIR}"
  if [[ "${SKIP_SERVICE}" -eq 0 ]]; then
    die "Use a path without spaces for systemd deploy (recommended: /opt/print-tracker)."
  fi
fi

if [[ -z "${LOGO_SOURCE}" && -f "${DEFAULT_LOGO_SOURCE}" ]]; then
  LOGO_SOURCE="${DEFAULT_LOGO_SOURCE}"
fi

HOST_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
if [[ -z "${HOST_IP}" ]]; then
  HOST_IP="localhost"
fi
KIOSK_BASE_URL="http://${HOST_IP}:${PORT}"

SECRET_KEY="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
)"

log "Project directory: ${APP_DIR}"
log "Service user/group: ${SERVICE_USER}:${SERVICE_GROUP}"
log "Kiosk URL base: ${KIOSK_BASE_URL}"

if [[ "${SKIP_APT}" -eq 0 ]]; then
  log "Installing system packages (this can take several minutes)..."
  run_root apt-get update
  run_root apt-get install -y \
    git \
    python3-venv python3-pip python3-dev build-essential \
    cups cups-client cups-bsd \
    printer-driver-ptouch \
    avahi-daemon \
    usbutils
else
  warn "Skipping apt package install (--skip-apt)."
fi

if id -u "${SERVICE_USER}" >/dev/null 2>&1; then
  log "Adding ${SERVICE_USER} to lpadmin/lp groups..."
  run_root usermod -aG lpadmin,lp "${SERVICE_USER}" || true
else
  warn "User ${SERVICE_USER} not found; skipping usermod."
fi

log "Preparing Python environment..."
python3 -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/pip" install --upgrade pip
"${VENV_DIR}/bin/pip" install -r "${APP_DIR}/requirements.txt" gunicorn

log "Creating app directories..."
mkdir -p "${INSTANCE_DIR}" "${LABEL_DIR}" "${ASSETS_DIR}"

if [[ -n "${LOGO_SOURCE}" ]]; then
  if [[ -f "${LOGO_SOURCE}" ]]; then
    cp "${LOGO_SOURCE}" "${LOGO_DEST}"
    log "Copied logo to ${LOGO_DEST}"
  else
    warn "Logo source not found: ${LOGO_SOURCE}. Label logo will fall back to text."
  fi
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  cp "${APP_DIR}/.env.example" "${ENV_FILE}"
  log "Created ${ENV_FILE} from .env.example"
fi

log "Writing .env settings..."
EXISTING_SECRET_KEY="$(get_env_value "${ENV_FILE}" "SECRET_KEY")"
if [[ -z "${EXISTING_SECRET_KEY}" || "${EXISTING_SECRET_KEY}" == "change-this" || "${EXISTING_SECRET_KEY}" == "change-me" ]]; then
  set_env_value "${ENV_FILE}" "SECRET_KEY" "${SECRET_KEY}"
fi
set_env_value "${ENV_FILE}" "DATABASE_URL" "sqlite:////${INSTANCE_DIR#/}/print_tracker.db"
set_env_value "${ENV_FILE}" "LABEL_PRINT_MODE" "${PRINT_MODE}"
set_env_value "${ENV_FILE}" "LABEL_PRINTER_QUEUE" "${PRINTER_QUEUE}"
set_env_value "${ENV_FILE}" "LABEL_OUTPUT_DIR" "${LABEL_DIR}"
set_env_value "${ENV_FILE}" "KIOSK_BASE_URL" "${KIOSK_BASE_URL}"
set_env_value "${ENV_FILE}" "LABEL_STOCK" "DK1202"
set_env_value "${ENV_FILE}" "LABEL_DPI" "300"
set_env_value "${ENV_FILE}" "LABEL_ORIENTATION" "landscape"
set_env_value "${ENV_FILE}" "LABEL_QR_PAYLOAD_MODE" "url"
set_env_value "${ENV_FILE}" "LABEL_QR_SIZE_INCH" "0.5"
set_env_value "${ENV_FILE}" "LABEL_CUPS_MEDIA" "${LABEL_MEDIA}"
set_env_value "${ENV_FILE}" "LABEL_SAVE_LABEL_FILES" "true"
set_env_value "${ENV_FILE}" "LABEL_BRAND_TEXT" "NC State University Libraries Makerspace"
if [[ -f "${LOGO_DEST}" ]]; then
  set_env_value "${ENV_FILE}" "LABEL_BRAND_LOGO_PATH" "${LOGO_DEST}"
fi
set_env_value "${ENV_FILE}" "DEFAULT_PRINTER_NAME" "Makerspace"

EXISTING_STAFF_PASSWORD="$(get_env_value "${ENV_FILE}" "STAFF_PASSWORD")"
if [[ -z "${EXISTING_STAFF_PASSWORD}" ]]; then
  set_env_value "${ENV_FILE}" "STAFF_PASSWORD" "staffpw"
fi

if [[ "${SKIP_DB_INIT}" -eq 0 ]]; then
  log "Initializing database..."
  (cd "${APP_DIR}" && "${VENV_DIR}/bin/flask" --app run.py init-db)
else
  warn "Skipping DB initialization (--skip-db-init)."
fi

if [[ "${SKIP_CUPS}" -eq 0 ]]; then
  log "Enabling CUPS..."
  run_root systemctl enable --now cups
  log "Detected print devices:"
  if command -v lsusb >/dev/null 2>&1; then
    lsusb | grep -i brother || warn "No Brother USB device detected yet."
  else
    warn "lsusb not found. Install usbutils or skip this check."
  fi
  if command -v lpinfo >/dev/null 2>&1; then
    lpinfo -v | grep -Ei 'usb|brother|ql' || warn "No obvious QL USB backend listed yet."
  else
    warn "lpinfo not found. CUPS client tools may not be installed."
  fi
else
  warn "Skipping CUPS setup (--skip-cups)."
fi

if [[ "${SKIP_SERVICE}" -eq 0 ]]; then
  log "Writing systemd service..."
  run_root tee "/etc/systemd/system/${SERVICE_NAME}.service" >/dev/null <<EOF
[Unit]
Description=Print Tracker
After=network.target cups.service

[Service]
User=${SERVICE_USER}
Group=${SERVICE_GROUP}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${ENV_FILE}
Environment=PORT=${PORT}
ExecStart=${VENV_DIR}/bin/gunicorn --workers 2 --threads 2 --bind 0.0.0.0:${PORT} run:app
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
  run_root systemctl daemon-reload
  run_root systemctl enable --now "${SERVICE_NAME}"
else
  warn "Skipping systemd setup (--skip-service)."
fi

log "Verifying service status..."
if [[ "${SKIP_SERVICE}" -eq 0 ]]; then
  run_root systemctl --no-pager --full status "${SERVICE_NAME}" || true
fi

if [[ "${SKIP_CUPS}" -eq 0 ]]; then
  log "Current CUPS queues:"
  lpstat -e || true
fi

cat <<EOF

Deployment complete.

Next checks:
1) Open http://${HOST_IP}:${PORT}/kiosk/register
2) In CUPS, confirm queue "${PRINTER_QUEUE}" exists: http://localhost:631
3) Print a CUPS test page:
   lp -d ${PRINTER_QUEUE} /usr/share/cups/data/testprint
4) Submit one kiosk print and confirm label output.

Useful commands:
- Service logs: journalctl -u ${SERVICE_NAME} -f
- Restart app: sudo systemctl restart ${SERVICE_NAME}

Important post-deploy checks:
- Change STAFF_PASSWORD in ${ENV_FILE} from default "staffpw", then restart the service.
- If staff scan from iPad/phone on Pi AP mode, set KIOSK_BASE_URL in ${ENV_FILE} to the Pi AP address (example: http://192.168.4.1:${PORT}), then restart the service.

EOF
