import os
import logging
import json
import docker
import tarfile
import io
import socket

def list_files(container_id, path):
    try:
        client = docker.from_env()

        if container_id is None:
            container_id = socket.gethostname()
            path = f"/app{path}"

        container = client.containers.get(container_id)
        stream, _ = container.get_archive(path)
        tar_stream = io.BytesIO(b''.join(stream))

        path_prefix = path.strip('/') + '/'
        tree = {}

        with tarfile.open(fileobj=tar_stream, mode='r|*') as tar:
            for member in tar:
                rel_path = member.name.strip('/')
                if rel_path.startswith(path_prefix):
                    rel_path = rel_path[len(path_prefix):]

                if not rel_path:
                    continue

                parts = rel_path.split('/')
                current = tree
                for i, part in enumerate(parts):
                    is_last = (i == len(parts) - 1)
                    if is_last:
                        if member.isdir():
                            current.setdefault(part, {"files": []})
                        else:
                            current.setdefault("files", [])
                            current["files"].append(part)
                    else:
                        if part not in current:
                            current[part] = {"files": []}
                        current = current[part]

        # Clean empty folders/files
        def cleanup(d):
            if "files" in d and not d["files"]:
                del d["files"]
            for k, v in list(d.items()):
                if isinstance(v, dict):
                    cleanup(v)
                    if not v:
                        del d[k]

        cleanup(tree)
        return tree

    except Exception as e:
        print(f"Error: {e}")
        return {"Error": str(e)}

