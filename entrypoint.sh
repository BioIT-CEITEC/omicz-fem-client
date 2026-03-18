#!/bin/bash
set -e

# Environment variables from docker-compose
HOST_UID=${UID}
HOST_GID=${GID}
HOST_USER=${USER_NAME}
HOST_DOCKER_GID=${DOCKER_GID}

echo "Configuring container user: $HOST_USER ($HOST_UID:$HOST_GID)"

# -------------------------
# 1. Ensure group exists
# -------------------------
if ! getent group "$HOST_GID" >/dev/null; then
    groupadd -g "$HOST_GID" "$HOST_USER"
fi

# -------------------------
# 2. Ensure user exists
# -------------------------
if ! id -u "$HOST_USER" >/dev/null 2>&1; then
    useradd -m -u "$HOST_UID" -g "$HOST_GID" -s /bin/bash "$HOST_USER"
fi

# -------------------------
# 3. Fix docker group
# -------------------------
if getent group docker >/dev/null; then
    CONT_DOCKER_GID=$(getent group docker | cut -d: -f3)
    if [ "$CONT_DOCKER_GID" -ne "$HOST_DOCKER_GID" ]; then
        groupdel docker
    fi
fi

if ! getent group docker >/dev/null; then
    groupadd -g "$HOST_DOCKER_GID" docker
fi

usermod -aG docker "$HOST_USER"

# -------------------------
# 4. Fix ownership of app dir
# -------------------------
chown -R "$HOST_UID:$HOST_GID" /app

# -------------------------
# 5. Switch to correct user and run the app
# -------------------------
exec su -s /bin/bash "$HOST_USER" -c "python3 /app/receiver.py"