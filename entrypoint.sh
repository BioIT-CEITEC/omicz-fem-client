#!/bin/bash
set -e

# Environment variables from docker-compose
HOST_UID=${UID}
HOST_GID=${GID}
HOST_USER=${USER_NAME}
HOST_DOCKER_GID=${DOCKER_GID}

echo "Configuring container user: $HOST_USER ($HOST_UID:$HOST_GID)"

# -------------------------
# 1. Ensure host group exists and has correct GID
# -------------------------
EXISTING_GROUP=$(getent group "$HOST_GID" | cut -d: -f1)
if [ -n "$EXISTING_GROUP" ] && [ "$EXISTING_GROUP" != "$HOST_USER" ]; then
    # GID is taken by another group -> reassign it to a free GID >= 2000
    FREE_GID=$(awk -F: '{print $3}' /etc/group | sort -n | awk 'BEGIN{n=2000} {if ($1==n) n++} END{print n}')
    echo "GID $HOST_GID already taken by group $EXISTING_GROUP, reassigning to $FREE_GID"
    groupmod -g "$FREE_GID" "$EXISTING_GROUP"
fi

if ! getent group "$HOST_USER" >/dev/null; then
    groupadd -g "$HOST_GID" "$HOST_USER"
fi

# -------------------------
# 2. Ensure host user exists with correct UID
# -------------------------
EXISTING_UID_USER=$(getent passwd "$HOST_UID" | cut -d: -f1)
if id -u "$HOST_USER" >/dev/null 2>&1; then
    CURRENT_UID=$(id -u "$HOST_USER")
    if [ "$CURRENT_UID" -ne "$HOST_UID" ]; then
        if [ -n "$EXISTING_UID_USER" ] && [ "$EXISTING_UID_USER" != "$HOST_USER" ]; then
            FREE_UID=$(awk -F: '{print $3}' /etc/passwd | sort -n | awk 'BEGIN{n=2000} {if ($1==n) n++} END{print n}')
            echo "UID $HOST_UID already taken by user $EXISTING_UID_USER, reassigning to $FREE_UID"
            usermod -u "$FREE_UID" "$EXISTING_UID_USER"
        fi
        echo "Updating UID of $HOST_USER to $HOST_UID"
        usermod -u "$HOST_UID" "$HOST_USER"
    fi
else
    if [ -n "$EXISTING_UID_USER" ]; then
        FREE_UID=$(awk -F: '{print $3}' /etc/passwd | sort -n | awk 'BEGIN{n=2000} {if ($1==n) n++} END{print n}')
        echo "UID $HOST_UID already taken by user $EXISTING_UID_USER, reassigning to $FREE_UID"
        usermod -u "$FREE_UID" "$EXISTING_UID_USER"
    fi
    echo "Creating user $HOST_USER with UID $HOST_UID and GID $HOST_GID"
    useradd -m -u "$HOST_UID" -g "$HOST_GID" -s /bin/bash "$HOST_USER"
fi

# -------------------------
# 3. Fix docker group
# -------------------------
EXISTING_DOCKER_GROUP=$(getent group "$HOST_DOCKER_GID" | cut -d: -f1)
if [ -n "$EXISTING_DOCKER_GROUP" ] && [ "$EXISTING_DOCKER_GROUP" != "docker" ]; then
    FREE_GID=$(awk -F: '{print $3}' /etc/group | sort -n | awk 'BEGIN{n=2000} {if ($1==n) n++} END{print n}')
    echo "Docker GID $HOST_DOCKER_GID already taken by $EXISTING_DOCKER_GROUP, reassigning to $FREE_GID"
    groupmod -g "$FREE_GID" "$EXISTING_DOCKER_GROUP"
fi

if ! getent group docker >/dev/null; then
    echo "Creating docker group with GID $HOST_DOCKER_GID"
    groupadd -g "$HOST_DOCKER_GID" docker
else
    CONT_DOCKER_GID=$(getent group docker | cut -d: -f3)
    if [ "$CONT_DOCKER_GID" -ne "$HOST_DOCKER_GID" ]; then
        echo "Updating docker group GID from $CONT_DOCKER_GID to $HOST_DOCKER_GID"
        groupmod -g "$HOST_DOCKER_GID" docker
    fi
fi

# Add host user to docker group
usermod -aG docker "$HOST_USER"

# -------------------------
# 4. Fix ownership of /app
# -------------------------
chown -R "$HOST_UID:$HOST_GID" /app
chown -R "$HOST_UID:$HOST_GID" /sandbox

# -------------------------
# 5. Switch to host user and run receiver.py
# -------------------------

echo "Launching fem-client as $HOST_USER"
exec env \
    LOG_FILE="/app/receiver.log" \
    HOME="/home/$HOST_USER" \
    PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
    su "$HOST_USER" -s /bin/bash -c "python3 /app/receiver.py"