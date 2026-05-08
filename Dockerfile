FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /opt/odoo

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        fontconfig \
        gcc \
        git \
        libffi-dev \
        libjpeg-dev \
        libldap2-dev \
        libpq-dev \
        libsasl2-dev \
        libssl-dev \
        libxml2-dev \
        libxslt1-dev \
        node-clean-css \
        node-less \
        postgresql-client \
        wkhtmltopdf \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --home-dir /var/lib/odoo --shell /bin/bash odoo \
    && mkdir -p /etc/odoo /var/lib/odoo /opt/odoo/custom_addons \
    && chown -R odoo:odoo /etc/odoo /var/lib/odoo

COPY --chown=odoo:odoo odoo19 /opt/odoo/odoo19
COPY --chown=odoo:odoo custom_addons /opt/odoo/custom_addons
COPY docker/entrypoint.sh /entrypoint.sh

RUN pip install --upgrade pip setuptools wheel \
    && pip install -e /opt/odoo/odoo19 \
    && chmod +x /entrypoint.sh

USER odoo

EXPOSE 8069 8072

ENTRYPOINT ["/entrypoint.sh"]
CMD ["odoo"]
