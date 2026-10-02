# Arq workers: botany, weather, hub, plates. The deployment.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv
RUN adduser --system --group --no-create-home herbology

# Dependencies and the packages come from one install, after the source is in
# place. The usual trick — copy the manifest, install, then copy the source —
# cannot work here: `[tool.setuptools] packages` names five directories, and
# setuptools resolves them at install time, so installing against a lone
# pyproject.toml fails with "package directory 'app' does not exist".
COPY api/ /srv/api/
COPY workers/ /srv/workers/
COPY contracts/ /srv/contracts/
COPY fixtures/ /srv/fixtures/

RUN pip install --no-cache-dir /srv/api

ENV PYTHONPATH=/srv/api:/srv

# The mount points of the volumes this image writes to, created here and
# owned by the user it runs as. A fresh named volume is seeded from the
# image's directory at the mount point, ownership included; without this it
# comes up root-owned, and the first plan upload or plate write fails with a
# permission error that nothing in the stack file can fix.
RUN mkdir -p /srv/images/grounds /srv/images/plates /srv/images/photos \
    && chown -R herbology:herbology /srv/images

# Secrets arrive as files and are read in the moment before exec.
COPY infra/docker/entrypoint.sh /usr/local/bin/moh-entrypoint
RUN chmod 0555 /usr/local/bin/moh-entrypoint

USER herbology

# WORKER_MODULE picks the parts of the project: workers.weather.tasks, workers.botany.tasks, …
# Started through run_worker.py rather than the `arq` CLI: the CLI never sees
# the configured Redis (see that file), and every worker crash-looped on
# localhost:6379.
COPY infra/docker/run_worker.py /srv/run_worker.py
ENV WORKER_MODULE=workers.weather.tasks
ENTRYPOINT ["/usr/local/bin/moh-entrypoint"]
CMD ["python", "/srv/run_worker.py"]
