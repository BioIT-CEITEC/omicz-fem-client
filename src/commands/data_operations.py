import time
import subprocess
from pathlib import Path
from typing import List
from config import config
import os
import requests
import logging
import json
import shutil 
from requests_toolbelt.multipart.encoder import MultipartEncoder
import base64
import mimetypes


data_path=config.data_path
sandbox_path=config.sandbox_path
node_name=config.node_name

def send_generated_files(generated_files, task_id, user_id, execution_id):
    try:
        api_url = f"https://fl.dev.bsc.es/dt4h-fl/API/v1/data/file/{task_id}?user_id={user_id}&execution_id={execution_id}"

        # Logging the attempt to send generated files
        logging.info(f"Attempting to send generated files to {api_url}")
        auth = ("your_username", "your_password")
        headers = {'Content-Type': 'application/json'}

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
        response = requests.put(api_url, data=json_payload, headers=headers, auth=auth)

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
BASE_URL = "https://fl.dev.bsc.es/dt4h-fl/API/v1"
PUSH_FILE_CONTENT_URL = f"{BASE_URL}/data/push_file_content"

def send_file_bytes(file_uri, user_id, execution_id, username="your_username", password="your_password", timeout=60):
    try:
        url = f"{PUSH_FILE_CONTENT_URL}?user_id={user_id}&execution_id={execution_id}&file_uri={file_uri}"

        # Check if the file or directory exists
        if not os.path.exists(file_uri):
            # Constructing the path using the sandbox root
            file_path = os.path.join(sandbox_path, file_uri)
            if not os.path.exists(file_path):
                logging.error(f"File not found: {file_path}")
                return False, f"File not found: {file_path}"
        else:
            file_path = file_uri

        # Check if the path is a directory
        if os.path.isdir(file_path):
            logging.info(f"Directory found: {file_path}. Sending files inside the directory.")
            # Iterate over each file in the directory and send them
            for root, _, files in os.walk(file_path):
                for name in files:
                    full_path = os.path.join(root, name)
                    result, message = send_single_file(full_path, url, username, password, timeout)
                    if not result:
                        return False, message
            return True, "All files in the directory have been sent successfully."
        else:
            # Send the single file
            return send_single_file(file_path, url, username, password, timeout)

    except Exception as e:
        logging.error(f"Error sending file bytes: {e}")
        return False, f"Error sending file bytes: {e}"

def send_single_file(file_path, url, username, password, timeout):
    try:
        with open(file_path, "rb") as file:
            # Determine the content type of the file
            mime_type, _ = mimetypes.guess_type(file_path)

            # Set up the multipart form data
            files = {"files": (os.path.basename(file_path), file, mime_type)}

            # Send file content using HTTP POST request
            response = requests.post(url, auth=(username, password), files=files, timeout=timeout)

        if response.status_code == 200:
            logging.info(f"File bytes sent successfully for {file_path}.")
            return True, response.text
        else:
            logging.error(f"Failed to send file bytes for {file_path}. Status code: {response.status_code}, Response: {response.text}")
            return False, f"Failed to send file bytes for {file_path}. Status code: {response.status_code}, Response: {response.text}"
    
    except Exception as e:
        logging.error(f"Error sending file bytes for {file_path}: {e}")
        return False, f"Error sending file bytes for {file_path}: {e}"

def list_files(user_id: str, folder_path: str, subfolder: str = None) -> list:
    if folder_path == "sandbox_path":
        full_path = sandbox_path
    elif folder_path == "data_path":
        full_path = data_path
    else:
        if os.path.isabs(folder_path):
            if os.path.exists(folder_path):
                full_path = folder_path
            elif os.path.exists(f"/{folder_path}"):
                full_path = f"/{folder_path}"
            else:
                logging.error(f"Folder '{folder_path}' does not exist.")
                raise FileNotFoundError(f"Folder '{folder_path}' does not exist.")
        else:
            if os.path.exists(f"/{folder_path}"):
                full_path = f"/{folder_path}"
            else:
                full_path = os.path.join(data_path, folder_path, subfolder) if subfolder else os.path.join(data_path, folder_path)
                if not os.path.exists(full_path):
                    full_path = os.path.join(sandbox_path, user_id, folder_path, subfolder) if subfolder else os.path.join(sandbox_path, user_id, folder_path)

    logging.info(f"Using path: {full_path}")

    if not os.path.exists(full_path):
        logging.error(f"Folder '{full_path}' does not exist.")
        raise FileNotFoundError(f"Folder '{full_path}' does not exist.")
    if not os.path.isdir(full_path):
        logging.error(f"'{full_path}' is not a directory.")
        raise NotADirectoryError(f"'{full_path}' is not a directory.")

    files = os.listdir(full_path)
    return files

