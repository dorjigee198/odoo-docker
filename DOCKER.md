# Docker Deployment

Copy the sample environment file and set strong passwords:

```bash
cp .env.example .env
```

Build and start Odoo with PostgreSQL:

```bash
docker compose up -d --build
```

If `docker compose` is unavailable, install the Docker Compose plugin or enable
Docker Desktop WSL integration for this distro. Older installations may use
`docker-compose up -d --build` instead.

Follow the Odoo logs:

```bash
docker compose logs -f odoo
```

Open Odoo at:

```text
http://localhost:8069
```

The database data is stored in the `odoo-db-data` Docker volume. Odoo filestore
data is stored in the `odoo-web-data` Docker volume. Custom addons are mounted
from `./custom_addons` so addon code changes can be picked up without rebuilding
the image.

For production, place Nginx, Traefik, or another TLS-terminating reverse proxy
in front of Odoo and keep `ODOO_PROXY_MODE=True`.
