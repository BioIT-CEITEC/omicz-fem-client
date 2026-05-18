import os
import logging
import base64
from config import config
import json
import argparse
import sys

def list_files(user_id, execution_id, path, sandbox_fem):
    try:
        # Get DATA base paths from env
        data_base = os.environ.get("DATA_PATH", "/data")

        path = os.path.normpath(path)

        if path.startswith("/sandbox"):
            if not user_id or not execution_id:
                raise ValueError("user_id and execution_id are required for /sandbox paths.")
            target_path = os.path.join(sandbox_fem, str(user_id), str(execution_id))
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
        return {"error": str(e)}
    
def send_files_as_json(user_id: str, execution_id:str, sandbox_fem:str, file: str = None) -> str:
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
        sandbox_path = sandbox_fem
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
            "sandbox_execution": sandbox_path,
            "files": files_payload
        }
    
    except Exception as e:
        return {"error": str(e)}


def receive_files(user_id: str, execution_id:str, incoming_files:list, sandbox_fem:str) -> dict:
    """
    Receives base64-encoded files and stores them on disk.
    Expected format:
        - list of files: [{"relative_path": ..., "content_b64": ...}, ...]
    """

    if isinstance(incoming_files, str):
        incoming_files = json.loads(incoming_files)

    if not sandbox_fem:
        raise ValueError("Missing 'sandbox_fem' needed to store outputs")

    dest_dir = os.path.join(sandbox_fem, user_id, execution_id)

    try:
        # Build destination directory
        logging.info(f"Storing received file in: {dest_dir}")

        # Create directory if it doesn't exist
        os.makedirs(dest_dir, exist_ok=True)

    except Exception as e:
        logging.error(f"Could not create directory {dest_dir}: {e}")
        return {"error": str(e)}

    stored_files = []

    # Process each file entry
    for file_entry in incoming_files:
        try:
            file_name = file_entry.get("relative_path")
            content_b64 = file_entry.get("content_b64")

            if not file_name or not content_b64:
                raise ValueError("Missing 'relative_path' or 'content_b64' in a file entry")

            # Compute full storage path
            dest_path = os.path.join(dest_dir, file_name)

            # Decode Base64
            file_bytes = base64.b64decode(content_b64)

            # Write file to disk
            with open(dest_path, "wb") as f:
                f.write(file_bytes)

            logging.info(f"Stored file: {dest_path}")
            stored_files.append(dest_path)

        except Exception as e:
            logging.error(f"Error storing file {file_entry}: {e}")
            stored_files.append({"file_name": file_entry.get("file_name"), "error": str(e)})

    return {
        "status": "success",
        "files_stored": stored_files
    }


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Data operations CLI")

    # Command
    parser.add_argument("command", choices=[
        "list_files",
        "send_files",
        "receive_files"
    ])

    # All possible arguments (defined once)
    parser.add_argument("--user_id")
    parser.add_argument("--execution_id")
    parser.add_argument("--sandbox_fem")
    parser.add_argument("--path")
    parser.add_argument("--file")
    parser.add_argument("--incoming_files")

    args = parser.parse_args()

    try:
        if args.command == "list_files":
            result = list_files(
                args.user_id,
                args.execution_id,
                args.path,
                args.sandbox_fem
            )

        elif args.command == "send_files":
            result = send_files_as_json(
                args.user_id,
                args.execution_id,
                args.sandbox_fem,
                args.file
            )

        elif args.command == "receive_files":
            result = receive_files(
                args.user_id,
                args.execution_id,
                args.incoming_files,
                args.sandbox_fem
            )

        # Always output valid JSON to stdout
        print(json.dumps(result), flush=True)

        # If your function signals error via dict, exit non-zero
        if isinstance(result, dict) and "error" in result:
            sys.exit(1)
        else:
            sys.exit(0)

    except Exception as e:
        # Log to stderr (not stdout!)
        logging.exception("Unhandled error")

        error_output = {"error": str(e)}
        print(json.dumps(error_output), file=sys.stdout, flush=True)

        sys.exit(1)