#import time
#import subprocess
#from pathlib import Path
#from typing import List
from config import config
import os
import requests
import logging
import json
#import shutil 
#from requests_toolbelt.multipart.encoder import MultipartEncoder
#import base64
import mimetypes
import docker
import tarfile
import io

api_base_url = config.api_base_url
data_path=config.data_path
sandbox_path=config.sandbox_path
node_name=config.node_name

def send_generated_files(api_base_url, generated_files, task_id, execution_id, user_id, token):
    
    try:
        #api_url = f"https://fl.bsc.es/flmanager/API/v1/data/file/{task_id}?user_id={user_id}&execution_id={execution_id}"
        api_url = f"{api_base_url}/data/file/{task_id}?user_id={user_id}&execution_id={execution_id}"

        # Logging the attempt to send generated files
        logging.info(f"Attempting to send generated files to {api_url}")
        headers = {'Content-Type': 'application/json',
            "Authorization": f"Bearer {token}" }

        # Ensure generated_files is a valid list of strings
        if not isinstance(generated_files, list) or not all(isinstance(file, str) for file in generated_files):
            raise ValueError("generated_files must be a list of strings")

        # Convert file paths to absolute paths
        absolute_paths = [os.path.join(user_id, execution_id, file) for file in generated_files]
        
        # Include the node name in the payload
        payload = {
            "generated_files": absolute_paths,
            "node_name": node_name
        }
        
        json_payload = json.dumps(payload)

        # Use the json parameter to automatically set Content-Type: application/json
        response = requests.put(api_url, data=json_payload, headers=headers)

        if response.ok:
            # Logging successful file send
            logging.info("Generated files sent successfully.")
        else:
            # Logging failed file send with status code and response content
            logging.error(f"Failed to send generated files. Status code: {response.status_code}. Response content: {response.content}")

            # Raise an exception to propagate the error (optional, depending on your error handling strategy)
            response.raise_for_status()

    except requests.exceptions.RequestException as req_exception:
        # Logging request-related exceptions
        logging.error(f"Request exception while sending generated files. Error: {req_exception}")


# Constants
#BASE_URL = "https://fl.bsc.es/flmanager/API/v1"
#PUSH_FILE_CONTENT_URL = f"{BASE_URL}/data/push_file_content"

def send_file_bytes(api_base_url, sandbox_path, user_id, token, execution_id):
    """
    Send all files from the constructed sandbox path for a given user and execution ID.
    
    :param sandbox_path: The base sandbox path where the files are located.
    :param user: Dictionary containing user details (user_id, access_token).
    :param execution_id: The execution ID to construct the file path.
    :param node_name: The node name to construct the file_uri.
    :param timeout: Timeout for the HTTP request.
    :return: Tuple (status, message)
    """
    headers = {"Authorization": f"Bearer {token}"}

    # Construct the full directory path where files should exist
    constructed_path = os.path.join(sandbox_path, user_id, execution_id)
    
    # Check if the directory exists
    if not os.path.exists(constructed_path):
        logging.error(f"Directory not found: {constructed_path}")
        return False, f"Directory not found: {constructed_path}"

    # Get the list of files in the directory
    files_in_directory = os.listdir(constructed_path)
    if not files_in_directory:
        logging.error(f"No files found in the directory: {constructed_path}")
        return False, f"No files found in the directory: {constructed_path}"

    logging.info(f"Files found: {files_in_directory}")

    # Iterate over each file and send it
    for file_name in files_in_directory:
        full_file_path = os.path.join(constructed_path, file_name)

        if os.path.isfile(full_file_path):
            # Construct file_uri format: node_name:user_id/execution_id/filename.txt
            file_uri = f"{node_name}:{user_id}/{execution_id}/{file_name}"

            # Construct the URL
            url = f"{api_base_url}/data/push_file_content?execution_id={execution_id}"

            result, message = send_single_file(full_file_path, url, headers)
            if not result:
                return False, message
        else:
            logging.warning(f"Skipping non-file entry: {full_file_path}")

    return True, "All files in the directory have been sent successfully."

#    try:
        #url = f"{PUSH_FILE_CONTENT_URL}?user_id={user_id}&execution_id={execution_id}&file_uri={file_uri}"
#        url = f"{api_base_url}/data/push_file_content/?user_id={user_id}&execution_id={execution_id}&file_uri={file_uri}"

        # Check if the file or directory exists
#        if not os.path.exists(file_uri):
#            # Constructing the path using the sandbox root
#            file_path = os.path.join(sandbox_path, file_uri)
#            if not os.path.exists(file_path):
#                logging.error(f"File not found: {file_path}")
#                return False, f"File not found: {file_path}"
#        else:
#            file_path = file_uri

#        # Check if the path is a directory
#        if os.path.isdir(file_path):
#            logging.info(f"Directory found: {file_path}. Sending files inside the directory.")
#            # Iterate over each file in the directory and send them
#            for root, _, files in os.walk(file_path):
#                for name in files:
#                    full_path = os.path.join(root, name)
#                    result, message = send_single_file(full_path, url, username, password, timeout)
#                    if not result:
#                        return False, message
#            return True, "All files in the directory have been sent successfully."
#        else:
#            # Send the single file
#            return send_single_file(file_path, url, username, password, timeout)

#    except Exception as e:
#        logging.error(f"Error sending file bytes: {e}")
#        return False, f"Error sending file bytes: {e}"

def send_single_file(file_path, url, headers, timeout=30):
    """
    Sends a single file to the specified URL via HTTP POST.
    
    :param file_path: The path to the file to be sent.
    :param url: The URL to send the file to.
    :param headers: The HTTP headers to include with the request.
    :param timeout: The timeout for the HTTP request.
    :return: Tuple (status, message)
    """

    try:
        with open(file_path, "rb") as file:
            # Determine the content type of the file
            mime_type, _ = mimetypes.guess_type(file_path)

            # Set up the multipart form data
            files = {"files": (os.path.basename(file_path), file, mime_type)}

            # Send file content using HTTP POST request
            response = requests.post(url, headers=headers, files=files, timeout=timeout)

        if response.status_code == 200:
            logging.info(f"File bytes sent successfully for {file_path}.")
            return True, response.text
        else:
            logging.error(f"Failed to send file bytes for {file_path}. Status code: {response.status_code}, Response: {response.text}")
            return False, f"Failed to send file bytes for {file_path}. Status code: {response.status_code}, Response: {response.text}"
    
    except Exception as e:
        logging.error(f"Error sending file bytes for {file_path}: {e}")
        return False, f"Error sending file bytes for {file_path}: {e}"

def list_files(container_id, path):
    client = docker.from_env()

    try:
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
                        # File or folder
                        if member.isdir():
                            current.setdefault(part, {"files": []})
                        else:
                            # Add file to 'files' list of current folder
                            current.setdefault("files", [])
                            current["files"].append(part)
                    else:
                        # Go deeper into subfolder
                        if part not in current:
                            current[part] = {"files": []}
                        current = current[part]

        # Clean up empty "files": [] lists 
        def cleanup(d):
            if "files" in d and not d["files"]:
                del d["files"]
            for k, v in list(d.items()):
                if isinstance(v, dict):
                    cleanup(v)
                    if not v:  # remove empty dicts
                        del d[k]

        cleanup(tree)
        return tree

    except Exception as e:
        print(f"Error: {e}")
        return {f"Error: {e}"}

