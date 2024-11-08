import subprocess
import logging
import threading
from .utils import *
from .data_operations import *
from config import config
import requests

class DockerLauncher:
    def __init__(self, task_info, task_id, execution_id, logger=None, user_id=None):
        self.task_info = task_info
        self.task_id = task_id
        self.execution_id = execution_id
        self.logger = logger
        self.user_id = user_id
        self.sandbox_path = config.sandbox_path
        self.data_path = config.data_path

    def construct_docker_command(self):
        command = ["docker", "run", "-d"]
        memory = self.task_info.get("memory", "")
        device = self.task_info.get("device", "")
        cap_add = self.task_info.get("cap_add", [])
        cap_drop = self.task_info.get("cap_drop", [])

        if memory:
            command += ["--shm-size=" + memory]
        if device:
            command += ["--device=" + device]
        if cap_add:
            if isinstance(cap_add, list):
                for cap in cap_add:
                    command += ["--cap-add=" + cap]
            else:
                command += ["--cap-add=" + cap_add]
        if cap_drop:
            if isinstance(cap_drop, list):
                for cap in cap_drop:
                    command += ["--cap-drop=" + cap]
            else:
                command += ["--cap-drop=" + cap_drop]

        for volume in self.task_info.get("volumes", []):
            host_path = volume.get("host_path", "")
            container_path = volume.get("container_path", "")
            execution_dir = os.path.join(self.sandbox_path, self.user_id, self.execution_id)
            os.environ["EXECUTION_DIR"] = execution_dir
            host_path = host_path.replace("$SANDBOX_PATH", self.sandbox_path)
            host_path = host_path.replace("$DATA_PATH", self.data_path)
            host_path = host_path.replace("$EXECUTION_DIR", execution_dir)
            container_path = container_path.replace("$DATA_PATH", self.data_path)
            container_path = container_path.replace("$SANDBOX_PATH", self.sandbox_path)
            container_path = container_path.replace("$EXECUTION_DIR", execution_dir)
            if host_path.startswith('$'):
                env_variable = host_path[1:]
                host_path = os.environ.get(env_variable, '')
            if container_path.startswith('$'):
                env_variable = container_path[1:]
                container_path = os.environ.get(env_variable, '')
            command += ["-v", f"{host_path}:{container_path}"]

        persistent = self.task_info.get("persistent", "")
        if persistent:
            command += ["-v", f"{self.sandbox_path}:{self.sandbox_path}"]

        for var_env, var_value in self.task_info.get("var_envs", {}).items():
            if var_value.startswith('$'):
                env_variable = var_value[1:]
                env_value = os.environ.get(env_variable, '')
                command += ["-e", f"{var_env}={env_value}"]
            else:
                command += ["-e", f"{var_env}={var_value}"]

        port_mappings = self.task_info.get("port_mappings", [])
        if isinstance(port_mappings, list):
            for mapping in port_mappings:
                container_port = mapping.get("container_port", "")
                host_port = mapping.get("host_port", "")
                if container_port and host_port:
                    command += ["-p", f"{host_port}:{container_port}"]
        elif isinstance(port_mappings, dict):
            container_port = port_mappings.get("container_port", "")
            host_port = port_mappings.get("host_port", "")
            if container_port and host_port:
                command += ["-p", f"{host_port}:{container_port}"]

        docker_image_info = self.task_info.get("image", {})
        docker_image_name = docker_image_info.get("url", "")
        docker_image_cmd = docker_image_info.get("cmd", "")

        if not docker_image_name:
            raise ValueError("Docker image name is empty")

        command += [docker_image_name]

        if docker_image_cmd:
            command += docker_image_cmd.split()

        return command

    def start_tool(self):
        docker_command = self.construct_docker_command()
        full_command = " ".join(docker_command)
        if self.logger:
            self.logger.info(f"Executing Docker command: {full_command}")
        check = subprocess.run(full_command, shell=True, capture_output=True)

        if self.logger:
            # Log stdout and stderr from subprocess.run for both success and failure cases
            self.logger.info(f"subprocess stdout: {check.stdout.decode().strip()}")
            self.logger.info(f"subprocess stderr: {check.stderr.decode().strip()}")

        if check.returncode == 0:
            response = check.stdout.decode().strip()
            container_id = response.strip()
            if self.logger:
                self.logger.info(f"Tool started successfully for task_id: {self.task_id}")
                self.logger.info(f"Container ID: {container_id}")

            if container_id:
                if self.logger:
                    self.logger.info(f"Starting log capture thread for container_id: {container_id}")
                logs_thread = threading.Thread(
                    target=capture_docker_logs,
                    args=(container_id, self.execution_id, self.task_id, self.logger, self.user_id)
                )
                logs_thread.start()
                return container_id
            else:
                error_message = f"No container ID received for task_id {self.task_id}"
                if self.logger:
                    self.logger.error(error_message)
                return error_message


        else:
            error_message = (
                f"Error starting Docker tool for task_id {self.task_id}.\n"
                f"Exit code: {check.returncode}\n"
                f"Error output: {check.stderr.decode().strip()}"
            )
            if self.logger:
                self.logger.error(error_message)
            return error_message

class GenericLauncher:
    def __init__(self, task_info, task_id, execution_id, logger=None, user_id=None):
        self.task_info = task_info
        self.task_id = task_id
        self.execution_id = execution_id
        self.logger = logger
        self.user_id = user_id
        self.config_dir = os.path.join(config.sandbox_path, "config", task_id)
        os.makedirs(self.config_dir, exist_ok=True)

    def start_tool(self):
        self.logger.info(f"Generic launcher called for {self.task_info}")
        source_code_info = self.task_info.get("source_code", {}) 
        source_code_url = source_code_info.get("url", "")
        self.logger.info(f"Fetching source code from URL: {source_code_url} for task {self.task_id}...")

        if fetch_source_code(self.task_info, self.logger):
            self.logger.info(f"Source code fetched successfully for task {self.task_id}.")
            return True
        else:
            self.logger.error(f"Failed to fetch source code for task {self.task_id}.")
        return False
