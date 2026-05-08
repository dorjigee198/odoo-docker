#!/usr/bin/env bash
set -euo pipefail

CONFIG_FILE="${ODOO_CONFIG_FILE:-/etc/odoo/odoo.conf}"

write_config() {
    mkdir -p "$(dirname "$CONFIG_FILE")"

    cat > "$CONFIG_FILE" <<EOF
[options]
addons_path = /opt/odoo/odoo19/addons,/opt/odoo/custom_addons
data_dir = /var/lib/odoo

admin_passwd = ${ODOO_ADMIN_PASSWORD:-change-me}

db_host = ${ODOO_DB_HOST:-db}
db_port = ${ODOO_DB_PORT:-5432}
db_user = ${ODOO_DB_USER:-odoo}
db_password = ${ODOO_DB_PASSWORD:-odoo}
db_name = ${ODOO_DB_NAME:-dorji}
dbfilter = ${ODOO_DBFILTER:-^dorji$}

http_enable = True
http_interface = 0.0.0.0
http_port = ${ODOO_HTTP_PORT:-8069}
gevent_port = ${ODOO_GEVENT_PORT:-8072}

proxy_mode = ${ODOO_PROXY_MODE:-True}
workers = ${ODOO_WORKERS:-0}
max_cron_threads = ${ODOO_MAX_CRON_THREADS:-2}
log_level = ${ODOO_LOG_LEVEL:-info}
list_db = ${ODOO_LIST_DB:-False}
EOF
}

if [[ "${1:-}" == "odoo" ]]; then
    write_config
    exec python /opt/odoo/odoo19/odoo-bin -c "$CONFIG_FILE"
fi

exec "$@"
