# FEM-client image. One image for both deployments: docker-compose.yml here and the
# manifests in k8s/ run it with the same user, the same mounts and the same entrypoint.
#
# What it no longer carries, and why:
#   - no docker CLI, docker-compose or gosu: tasks are submitted to a WES API, so the
#     container starts no containers and never sees /var/run/docker.sock;
#   - no entrypoint.sh: there is no UID/GID remapping and no chown step, because the
#     container never runs as root;
#   - no build toolchain: nothing is compiled at runtime.
#
# It runs as UID 1000 (runAsUser in the manifests) and works with a read-only root
# filesystem: everything it writes to is a mount.
FROM python:3.10-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        bash curl jq git ca-certificates openssl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY ./app/ /app/

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Mount points supplied by the deployment: /app/config (ro), /sandbox, /var/log/fem, /tmp.
# No /data: the datasets are mounted by the WES workers, not by this container.
#
# The two writable ones are created here, owned by the runtime user. On Kubernetes an
# emptyDir/PVC with fsGroup 1000 would cover it, but a docker-compose named volume is
# initialised from the image: an absent or root-owned directory becomes a root-owned
# volume that uid 1000 cannot write, and the receiver dies on its own log file.
RUN install -d -o 1000 -g 1000 /sandbox /var/log/fem

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER 1000

ENTRYPOINT ["python3", "/app/receiver.py"]
