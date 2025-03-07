import json
import os
import logging
import subprocess
import re
import threading
from .utils import *
from .data_operations import *
from .check_resources import *
from config import config
import requests

api_base_url=config.api_base_url
def fetch_task_info(api_base_url, task_id):
    try:
        # Make a request to the endpoint to get the tool information
        #response = requests.get(f"https://fl.bsc.es/flmanager/API/v1/tools/{tool_id}")
        response = requests.get(f"{api_base_url}/tasks/{task_id}")
        task_info = response.json()
        return task_info
    except Exception as e:
        print(f"Error fetching tool information: {e}")
        return None


def replace_api_placeholders(cmd, config_json, json_action):
    """
    Replaces placeholders in the cmd string surrounded by {} with corresponding values from the config JSON.
    - Handles lists by repeating flags for each item in the list.
    - Handles dictionaries by converting them to JSON strings.
    - Retains single quotes around the placeholder while replacing.
    """
    # Find all placeholders in the command surrounded by {}
    placeholders = re.findall(r'{([^}]+)}', cmd)

    for placeholder in placeholders:
        # Get the replacement value from the config JSON under "submit_run"
        replacement_value = config_json.get(str(json_action), {}).get(placeholder)

        if replacement_value is None:
            # Log missing placeholder for debugging
            logging.info(f"No value found for placeholder: {placeholder}. Leaving as is.")
            cmd = cmd.replace(f"\'{{{placeholder}}}\'", '')
            continue

        if isinstance(replacement_value, list):
            # If the replacement is a list, repeat the flag for each item in the list
            flag_match = re.search(r'(-\w+)\s*\'\{' + re.escape(placeholder) + '\}\'', cmd)  
            if flag_match:
                flag_name = flag_match.group(1)  # Extract the flag, e.g., "-H"
                logging.info(f"flag: {flag_name}")
                # Apply '-H' to each item in the list and wrap each with single quotes
                repeated_flags = " ".join(
                    f"{flag_name} '{strip_quotes(str(item))}'" for item in replacement_value
                )
                cmd = re.sub(rf'{re.escape(flag_name)}\s*\'\{{{placeholder}}}\'' , repeated_flags, cmd)
            else:
                # Handle the list without a flag, wrap each item in single quotes
                logging.info(f"Flag not found for placeholder: {placeholder}. Replacing without flag.")
                repeated_values = " ".join(f"'{strip_quotes(str(item))}'" for item in replacement_value)
                cmd = cmd.replace(f"\'{{{placeholder}}}\'", repeated_values)

        elif isinstance(replacement_value, dict):
            # Convert dictionaries to JSON strings and wrap with single quotes
            replacement_value = json.dumps(replacement_value)
            cmd = cmd.replace(f"\'{{{placeholder}}}\'", f"'{replacement_value}'")  # Keep quotes

        else:
            # Replace the placeholder with the value directly, stripping quotes and wrapping with single quotes
            cmd = cmd.replace(f"\'{{{placeholder}}}\'", f"'{strip_quotes(str(replacement_value))}'")

    # Log final cmd for debugging
    logging.info(f"Command after replacing API placeholders: {cmd}")

    return cmd

def strip_quotes(value):
    """
    Removes initial and final double quotes from a string if present.
    """
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    return value

def template_format(data, template):
    """
    This function takes either a dictionary or a list of dictionaries as input and applies a string template 
    to generate formatted strings. The template placeholders are dynamically replaced with the corresponding 
    key-value pairs from the data. 
    """
    final_strings = []
    # Check if the data is a list of dictionaries
    if isinstance(data, list):
        for item in data:
            # Use **item to unpack keys and values into the template
            final_strings.append(template.format(**item))
    elif isinstance(data, dict):
        for key, value in data.items():
            # For flat dictionaries, format with key and value
            final_strings.append(template.format(key=key, value=value))
    else:
        raise ValueError("Data must be a dictionary or a list of dictionaries")
    
    return final_strings


def build_cwl_command(task_command, parametric_args=None):
    """
    This function builds a cmd string builded from the cwl compatible information iside the 'command' block of the DDBB
    """
    # Extract the base command and args from task_command
    base_command = task_command['base']
    args = task_command.get('args', [])

    # Validate that 'args' is a list
    if not isinstance(args, list):
        raise TypeError(f"'args' must be a list, but got {type(args).__name__}")

    # If args is empty, return just the base command
    if not args:
        return base_command

    # Validate that each item in 'args' is a dictionary
    if not all(isinstance(arg, dict) for arg in args):
        raise ValueError("Each item in 'args' must be a dictionary.")

    # Sort args based on the 'position' key if it exists
    args = sorted(args, key=lambda x: x.get('position', float('inf')) if 'position' in x else float('inf'))

    # Build the command
    command_parts = [base_command]

    # Loop through arguments
    for arg in args:
        arg_id = arg['id']
        default_value = arg['default_value']
        prefix = arg['prefix']
        separate = arg['separate']
        required = arg['required']

        # Determine the value to use
        if parametric_args and arg_id in parametric_args:
            value = parametric_args[arg_id]
        elif required:
            if default_value != "":
                value = default_value
            else:
                raise ValueError(f"Required argument '{arg_id}' is missing and has no default value.")
        else:
            continue

        # Add the argument to the command if it has a value
        if separate:
            command_parts.append(f"{prefix} {value}")
        else:
            command_parts.append(f"{prefix}{value}")

    # Join the command parts with spaces and return
    return ' '.join(command_parts)

def clean_composed_command(command):
    # This regex pattern matches flags with optional values and checks for empty values after the '='
    pattern = r'(--?\w+[-\w]*)(=)([^\s-]*)'  # matches flag=-value (allowing for no value)
    
    # Function to process and remove the invalid arguments
    def replace_invalid_arguments(match):
        flag, equal_sign, value = match.groups()
        # If the value is empty (or a flag starts with a '-'), skip this argument
        if not value or re.match(r"^-\w", value):  
            return ""  # Remove this argument entirely
        return match.group(0)  # Return the match as it is if the value is valid

    # Apply regex replacement to the command
    cleaned_command = re.sub(pattern, replace_invalid_arguments, command)
    
    # Check if the last element is a flag or flag followed by '=' with no value
    # This pattern checks if the last part is a flag or a flag with '=' but no value after it
    cleaned_command = re.sub(r'(--?\w+[-\w]*)(=?)(\s*)$', '', cleaned_command)

    # Clean up extra spaces (if any) after removal of arguments
    cleaned_command = re.sub(r'\s+', ' ', cleaned_command).strip()
    
    return cleaned_command

def run_tool(api_base_url, task_id, execution_id, parametric_args, user_id, token, json_action):

    try: 
        # Define directories
        user_folder = os.path.join(config.sandbox_path, user_id)
        execution_folder = os.path.join(user_folder, execution_id)

        # Check and create directories if they don't exist
        if not os.path.exists(user_folder):
            os.makedirs(user_folder)

        if not os.path.exists(execution_folder):
            os.makedirs(execution_folder)
            
    except Exception as e:
        error_message = f"Execution folder {execution_folder} could not be created: {e}"
        logger.info(error_message)
        return error_message 
       
    
    try:
        logger = logging.getLogger("receiver")
        logger.info(f"Starting {json_action} command for execution_id: {execution_id}, user_id: {user_id}")
                
        # Load the JSON launcher configuration
        json_launcher_path = config.json_launcher
        logger.info(f"json_launcher: {json_launcher_path}")
        if not json_launcher_path or not os.path.isfile(json_launcher_path):
            raise FileNotFoundError(f"JSON launcher configuration file not found at: {json_launcher_path}")
        
        with open(json_launcher_path, "r") as json_file:
            json_config = json.load(json_file)

        #Fetch Task info or Execution info from DDBB:
        if json_action == "submit_run":
            task_info = fetch_task_info(api_base_url, task_id)
            pre_checks_result = pre_checks()
            #logger.info(f"task_info: {task_info}")
            #logger.info(f"Pre-checks result: {pre_checks_result}")
        
            if task_id == "health-check":
                return pre_checks_result
        else: 
            #If there's no task/tool info provided, fetch the execution info
            headers = {'Content-Type': 'application/json',
                "Authorization": f"Bearer {token}" }
            response = requests.get(f"{api_base_url}/executions/{execution_id}", headers=headers)
            execution = response.json()
            # Extract process_info list from the execution
            process_info_list = execution.get("result", {}).get("process_info", [])

            # Find the process_info entry matching the specified node
            task_info = next(
                (info for info in process_info_list if info.get("node") == config.node_name and info.get("task_id") == task_id),
                None  # Default value if no match is found
            )

            if not task_info:
                raise ValueError("Not task_info or execution_info downloaded from DDBB")
        logger.info(f"Task info correctly fetched for {json_action}")
        
        # Extract command and arguments from the JSON
        cmd = json_config.get(str(json_action), {}).get("cmd", {})
        if not cmd:
            raise ValueError("Command to run is not defined in the JSON configuration")
        
        # Ensure cmd is always a string
        if isinstance(cmd, list):
            cmd = "\n".join(cmd)
        else:
            cmd = cmd
        
        if cmd.startswith('curl -X'):
            cmd = replace_api_placeholders(cmd, json_config, json_action)

    except Exception as e:
        error_message = f"An error occurred while loading the json file: {e}"
        logger.info(error_message)
        return error_message 
    
    try:

        # Extract mapping dictionaries from the json_config
        task_info_vars = json_config.get("task_info_vars", {})
        system_var_handler = json_config.get("system_var_handler", {})
        site_vars = json_config.get("site_vars", {})

        # Find all placeholders in the command string
        placeholder_pattern = re.compile(r"%%(.*?)%%")
        resolved_cmd = cmd

        # Function arguments to check for placeholders
        argument_values = {
            "api_base_url": api_base_url,
            "task_id": task_id,
            "execution_id": execution_id,
            "user_id": user_id,
            "token": token
        }

        processed_placeholders = set()  # To keep track of placeholders already processed

        while True:
            # Find all placeholders in the current command
            placeholders = placeholder_pattern.findall(resolved_cmd)
            placeholders = [ph for ph in placeholders if ph not in processed_placeholders]

            if not placeholders:  # Break if no new placeholders remain
                break

            for placeholder in placeholders:
                processed_placeholders.add(placeholder)

                # Build the task_command with the CWL format for that specific placeholder:
                if placeholder == "TASK_COMMAND":
                    task_command = task_info.get("command")
                    value = build_cwl_command(task_command, parametric_args=parametric_args)
                    if cmd.startswith('curl -X'):
                        # Convert the command into a list format as a string
                        value_as_list_str = "[" + ", ".join(f'"{part}"' for part in value.split()) + "]"
                        
                        # Replace the placeholder with the formatted list string
                        resolved_cmd = resolved_cmd.replace(f'"%%{placeholder}%%"', value_as_list_str)
                    else:
                        resolved_cmd = resolved_cmd.replace(f"%%{placeholder}%%", str(value))
                    continue

                # Try resolving the placeholder from function arguments
                if placeholder in site_vars:
                    resolved_cmd = resolved_cmd.replace(f"%%{placeholder}%%", site_vars.get(placeholder))
                    continue

                # Then, try resolving from task_info using task_info_vars
                task_info_path = task_info_vars.get(placeholder)
                if task_info_path:
                    if isinstance(task_info_path, list):  # Resolve nested keys
                        value = task_info
                        for key in task_info_path:
                            if value is None:  # If any level is missing, stop
                                break
                            value = value.get(key)

                    elif isinstance(task_info_path, str):  # Resolve top-level keys
                        value = task_info.get(task_info_path)

                    if value is not None:
                        # Replace the placeholder with the resolved value
                        resolved_cmd = resolved_cmd.replace(f"%%{placeholder}%%", str(value))
                        # Check if the resolved value introduces new placeholders
                        continue

                # Replace the placeholders that need the system template:
                if placeholder in system_var_handler:
                    task_info_data = task_info.get(placeholder.lower())
                    if task_info_data:  
                        sys_template = system_var_handler.get(placeholder)
                        value = template_format(task_info_data, sys_template)
                        resolved_cmd = resolved_cmd.replace(f"%%{placeholder}%%", " ".join(value))
                    else:
                        resolved_cmd = resolved_cmd.replace(f"%%{placeholder}%%", "")
                    continue

                # Try resolving the placeholder from function arguments
                if placeholder in argument_values:
                    resolved_cmd = resolved_cmd.replace(f"%%{placeholder}%%", str(argument_values[placeholder]))
                    continue

                # Try resolving the placeholder from environment variables
                env_value = os.environ.get(placeholder)
                if env_value is not None:
                    resolved_cmd = resolved_cmd.replace(f"%%{placeholder}%%", env_value)
                    continue

                # If the placeholder cannot be resolved, raise an error
                raise KeyError(f"Placeholder {placeholder} could not be resolved from environment or task_info")
        
        resolved_cmd = clean_composed_command(resolved_cmd)

        logger.info(f"Resolved command: {resolved_cmd}")
        
        # Run the command
        process = subprocess.run(resolved_cmd, shell=True, capture_output=True)

        # If the image is not found, handle the error
        if process.returncode != 0:
            stderr = process.stderr.decode().strip()
            if "Unable to find image" in stderr:
                logger.info("Docker image not found. Attempting docker pull...")

                # Get source code URL from task_info
                image_url = task_info.get("image", {}).get("url")
                if image_url:
                    # Attempt to pull the Docker image using the URL
                    pull_command = f"docker pull {image_url}"
                    pull_process = subprocess.run(pull_command, shell=True, capture_output=True)
                    
                    if pull_process.returncode == 0:
                        logger.info(f"Docker image {image_url} pulled successfully.")

                        # Re-run the Docker command
                        process = subprocess.run(resolved_cmd, shell=True, capture_output=True)
        
        if process.returncode == 0:
            response = process.stdout.decode().strip()
            logger.info(f"Command executed successfully: {response}")
            
            # Simulate capturing container ID (Docker outputs the container ID on success)
            container_id = response.strip()  # The container ID should be the first line of stdout
            
            # Log container ID and proceed with file generation simulation
            logger.info(f"Container ID: {container_id}")
            
            # Simulate capturing logs (you can adapt this to your own log capture function if needed)
            logger.info(f"Starting log capture for container: {container_id}")
            # Assuming `capture_docker_logs` function exists to capture logs from the container
            logs_thread = threading.Thread(
                target=capture_docker_logs, 
                args=(container_id, execution_id, task_id, logger, user_id)
            )
            logs_thread.start()

            return response, container_id
            
            # Simulate waiting for files to be generated (this can be replaced with a more accurate wait/check)
            # sandbox_path = os.environ.get("SANDBOX_PATH", "/sandbox")
            # generated_files_path = os.path.join(sandbox_path, user_id, execution_id)
            # time.sleep(5)  # Adjust this depending on how long the container takes to generate the files
            
            # # Assuming files are generated in this folder, list them
            # if os.path.exists(generated_files_path):
            #     generated_files = os.listdir(generated_files_path)
            #     logger.info(f"Generated files: {generated_files}")
            #     send_generated_files(api_base_url, generated_files, task_id, execution_id, user_id, token)
                
            #     return response, generated_files
            # else:
            #     error_message = f"Generated files not found at {generated_files_path}"
            #     logger.error(error_message)
            #     return error_message
        else:
            error_message = (
                f"Error executing command.\n"
                f"Exit code: {process.returncode}\n"
                f"Stdout: {process.stdout.decode().strip()}\n"
                f"Stderr: {process.stderr.decode().strip()}"
            )
            logger.error(error_message)
            return error_message
    except Exception as e:
        error_message = f"An error occurred: {e}"
        logger.info(error_message)
        return error_message



# if __name__ == '__main__': # TODO Decide whether to keep command line usage, needs to read config
#     parser = argparse.ArgumentParser()
#     parser.add_argument("--task_id", help="ID of the task to run", type=str)
#     parser.add_argument("--user_id", help="User ID", type=str)
#     args = parser.parse_args()
    
    
#     logging.basicConfig(level=logging.INFO)
    
#     logger = logging.getLogger(__name__)
#     logger.info(f"Running tool for task_id: {args.task_id}")
    
#     run_tool(api_base_url, args.task_id, execution_id, args.user_id)
