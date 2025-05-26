from urllib.parse import urlparse
from config import config
import subprocess

import os
import pwd
import subprocess
from urllib.parse import urlparse

def fetch_source_code(task_info, logger):
    try:
        source_code_info = task_info.get("source_code", {})
        source_code_url = source_code_info.get("url", "")
        commit_hash = source_code_info.get("commit_hash", "")
        sandbox_path = config.sandbox_path

        if not source_code_url:
            logger.error("Source code URL is not provided in the tool definition.")
            return False

        # Extract the repository name from the Git URL
        repo_name = os.path.splitext(os.path.basename(urlparse(source_code_url).path))[0]

        source_code_path = os.path.join(sandbox_path, repo_name)

        # Get the user information
        current_user = os.getlogin()

        user_info = pwd.getpwnam(current_user)
        uid = user_info.pw_uid
        gid = user_info.pw_gid

        def demote():
            os.setgid(gid)
            os.setuid(uid)

        if os.path.exists(source_code_path):
            # If it exists, perform a git pull to update to the latest commit
            logger.info(f"Source code directory already exists. Performing git pull.")
            subprocess.run(["git", "pull"], cwd=source_code_path, capture_output=True, preexec_fn=demote)
        else:
            # If it doesn't exist, perform a git clone
            logger.info(f"Source code directory does not exist. Performing git clone.")
            subprocess.run(["git", "clone", source_code_url, source_code_path], capture_output=True, preexec_fn=demote)

        # If a commit hash is provided, perform a git checkout
        if commit_hash:
            logger.info(f"Checking out specific commit: {commit_hash}")
            subprocess.run(["git", "checkout", commit_hash], cwd=source_code_path, capture_output=True, preexec_fn=demote)

        return True
    except Exception as e:
        logger.error(f"Error fetching source code: {e}")
        return False

def capture_docker_logs(container_id, execution_id, task_id, logger, user_id=None):
    try:
        # Create directories for logs
        user_folder = os.path.join('sandbox', user_id) if user_id else 'sandbox'
        os.makedirs(user_folder, exist_ok=True)

        execution_folder = os.path.join(user_folder, execution_id)
        os.makedirs(execution_folder, exist_ok=True)
        if not os.path.exists(execution_folder):
            raise RuntimeError(f"Execution folder {execution_folder} could not be created.")

        # Define log file path
        docker_logs_file = os.path.join(execution_folder, f"{task_id}_docker_logs.txt")
        logger.info(f"Log file path: {docker_logs_file}")

        # Check container state (Running or Exited)
        status_command = f"docker inspect -f '{{{{.State.Running}}}}' {container_id}"
        status_process = subprocess.run(
            status_command, shell=True, capture_output=True, text=True
        )
        is_running = status_process.stdout.strip().lower() == "true"

        # Choose appropriate command based on state
        logs_command = f"docker logs {container_id}" if not is_running else f"docker logs -f {container_id}"
        logger.info(f"Logs command: {logs_command}, Running: {is_running}")

        # Fetch logs
        with open(docker_logs_file, "a") as log_file:
            process = subprocess.Popen(
                logs_command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
            for line in iter(process.stdout.readline, ""):
                log_file.write(line)
                log_file.flush()  # Ensure immediate writes to disk
                #logger.info(line.strip())  # Optional: Log to console for debugging

            process.wait()  # Wait for the logs process to finish
            logger.info(f"Container {container_id} logs capture completed.")

    except Exception as e:
        logger.error(f"Error capturing logs for container {container_id}: {e}")





def manage_docker_container(action, container_name):
    result = {}

    try:
        if action == "pull":
            # Check if the Docker image is available locally and pull if not
            check_output = subprocess.run(f"docker image inspect {container_name}", shell=True, capture_output=True)
            if check_output.returncode != 0:
                result['message'] = f"Docker image '{container_name}' not found locally. Pulling the image..."
                subprocess.run(f"docker pull {container_name}", shell=True, check=True)
            else:
                result['message'] = f"Docker image '{container_name}' is already available locally."
        elif action == "stop":
            # Stop the Docker container
            subprocess.run(f"docker stop {container_name}", shell=True, check=True)
            result['message'] = f"Docker container '{container_name}' stopped successfully."
        elif action == "remove":
            # Remove the Docker container
            subprocess.run(f"docker rmi {container_name}", shell=True, check=True)
            result['message'] = f"Docker container '{container_name}' removed successfully."
        else:
            result['message'] = f"Invalid action: {action}"
    except Exception as e:
        result['error'] = f"Error managing Docker container: {e}"

    return result



