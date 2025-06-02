import os
import logging
import docker
import tarfile
import io
import socket
import base64
from config import config

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
    
def send_files_as_json(user_id: str, execution_id:str, file: str = None) -> str:
    """
    Prepares a file or all files in a folder (recursively) as a JSON string
    suitable for sending via RabbitMQ. Includes base64-encoded file content and
    relative paths to replicate directory structure.

    Args:
        user_id (str): Logged user and owner of files. Checked at endpoint. 
        execution_id: folder of the execution and part of the path.
        file (str): file name is specific file is wanted instead of full execution folder.

    Returns:
        str: JSON string with file metadata and contents.
    
    Raises:
        FileNotFoundError: If the path does not exist.
    """

    try:

        # Convert file paths to absolute paths
        path = os.path.join("/app/sandbox", user_id, execution_id, file)
        logging.info(f"Sending file or folder: {path}")

        if not os.path.exists(path):
            raise FileNotFoundError(f"Path does not exist: {path}")

        files_payload = []

        if os.path.isfile(path):
            base_dir = os.path.dirname(path)
            files = [path]
        else:
            base_dir = path
            files = [
                os.path.join(root, filename)
                for root, _, filenames in os.walk(path)
                for filename in filenames
            ]

        for full_file_path in files:
            relative_path = os.path.relpath(full_file_path, base_dir).replace("\\", "/")

            dir_part, file_part = os.path.split(relative_path)
            new_file_name = f"{config.node_name}_{file_part}"
            relative_path = f"{dir_part}/{new_file_name}" if dir_part else new_file_name

            with open(full_file_path, 'rb') as f:
                file_bytes = f.read()

            files_payload.append({
                "relative_path": relative_path,
                "content_b64": base64.b64encode(file_bytes).decode('utf-8')
            })

        return {
            "base_dir": os.path.basename(base_dir),
            "files": files_payload
        }
    
    except Exception as e:
        print(f"Error: {e}")
        return {"Error": str(e)}
