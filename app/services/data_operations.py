import os
import logging
import base64
from config import config

def list_files(user_id, execution_id, path):
    try:
        # Get SANDBOX and DATA base paths from env
        sandbox_base = os.environ.get("SANDBOX_PATH", "/app/sandbox")
        data_base = os.environ.get("DATA_PATH", "/app/data")

        path = os.path.normpath(path)

        if path.startswith("/sandbox"):
            if not user_id or not execution_id:
                raise ValueError("user_id and execution_id are required for /sandbox paths.")
            target_path = os.path.join(sandbox_base, str(user_id), str(execution_id))
        elif path.startswith("/data"):
            # Trim "/data" and join any subpath
            sub_path = path[5:].lstrip("/")
            target_path = os.path.join(data_base, sub_path)
        else:
            raise ValueError("Path must start with /sandbox or /data.")

        if not os.path.exists(target_path):
            raise FileNotFoundError(f"Path does not exist: {target_path}")

        tree = {}

        for root, dirs, files in os.walk(target_path):
            # Calculate relative path from the root sandbox dir
            rel_root = os.path.relpath(root, target_path)
            if rel_root == ".":
                rel_root = ""

            # Navigate to the correct place in the tree
            parts = rel_root.split(os.sep) if rel_root else []
            current = tree
            for part in parts:
                current = current.setdefault(part, {})

            if files:
                current.setdefault("files", []).extend(files)

        # Clean empty 'files' keys and empty folders
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
        sandbox_path = os.environ.get('SANDBOX_PATH', '/app/sandbox')
        path = os.path.join(sandbox_path, user_id, execution_id, file)
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
