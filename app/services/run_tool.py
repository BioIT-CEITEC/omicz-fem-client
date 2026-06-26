import json
import os
import logging
import subprocess
import re
from .utils import *
from .data_operations import *
from .check_resources import *
from config import config
import ast
from services.check_resources import check_gpu

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
    for i, arg in enumerate(args):
        arg['_original_index'] = i  # Preserve original order for tie-breaking

    args = sorted(
        args,
        key=lambda x: (
            0 if isinstance(x['position'], int) else 1,  # positioned args first
            x['position'] if isinstance(x['position'], int) else float('inf'),
            x['_original_index']
        )
    )

    for arg in args:
        arg.pop('_original_index', None)


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
    """
    Cleans a command string by removing flags that have '=' or '=='
    with no value, empty quotes, or a single '-'.
    Preserves all other flags, including single-letter flags and
    flags followed by space and a value.
    Returns a single-line command.
    """

    # Pattern explanation:
    # 1. (--?\w[\w-]*)      => flag (single or double dash)
    # 2. (={1,2})            => = or ==
    # 3. (?:
    #       (["']{2}|-)      => empty quotes "" or '' or just -
    #       |                 => OR
    #       (?=\s|$|--)       => nothing follows (end, whitespace, or next flag)
    #    )
    pattern = r'(--?\w[\w-]*)(={1,2})(?:(["\']{2}|-)|(?=\s|$|--))'

    # Remove the invalid flags
    cleaned_command = re.sub(pattern, '', command)

    # Collapse all whitespace (spaces, tabs, newlines) into a single space
    cleaned_command = re.sub(r'\s+', ' ', cleaned_command).strip()

    return cleaned_command

def resolve_cmd_placeholders(json_config, json_action, cmd, argument_values=None, task_info=None, parametric_args=None): 

    logger = logging.getLogger("receiver")

    argument_values = argument_values or {}
    parametric_args = parametric_args or {}

    # Ensure cmd is always a string
    if isinstance(cmd, list):
        cmd = "\n".join(cmd)
    else:
        cmd = cmd
    
    if 'curl -X' in cmd:
        cmd = replace_api_placeholders(cmd, json_config, json_action)

    # Extract mapping dictionaries from the json_config
    task_info_vars = config.task_info_vars
    system_var_handler = json_config.get("system_var_handler", {})
    site_vars = json_config.get("site_vars", {})

    # Find all placeholders in the command string
    placeholder_pattern = re.compile(r"%%(.*?)%%")
    resolved_cmd = cmd

    for _ in range(50):
        placeholders = placeholder_pattern.findall(resolved_cmd)
        if not placeholders:
            break  # No more placeholders to process

        for placeholder in placeholders:
            
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

            # Try resolving the placeholder from command arguments
            if placeholder in parametric_args:
                resolved_cmd = resolved_cmd.replace(f"%%{placeholder}%%", str(parametric_args[placeholder]))
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

    return resolved_cmd

def run_tool(task_info, execution, parametric_args, user_id, public_ip, json_action, token):
    
    logger = logging.getLogger("receiver")

    try:
        # Apply different logic if json_action handles files
        FILE_ACTIONS = {"list_files", "send_files", "receive_files"}

        is_file_action = json_action in FILE_ACTIONS

        # File actions already receive raw execution_id
        if is_file_action:
            execution_id = execution
            task_id = "file_action"

        else:
            execution = json.loads(execution)
            execution_id = execution.get('execution_id')

            task_info = ast.literal_eval(task_info)
            task_id = task_info.get("_id")
    except Exception as e:
        error_message = f"Initialization failed: {e}"
        logger.info(error_message)
        return json.dumps({"error": error_message}), None

    # Dictionari of internal function variables
    argument_values = {
        "node_name": config.node_name,
        "api_base_url": config.api_base_url,
        "task_id": task_id,
        "execution_id": execution_id,
        "user_id": user_id,
        "sandbox_host": config.sandbox_path,
        "sandbox_fem": os.getenv("SANDBOX_PATH"),
        "sandbox_execution": "",
        "data_path": config.data_path, 
        "token": token
    }

    
    try:
        logger.info(f"Starting {json_action} command for execution_id: {execution_id}, user_id: {user_id}")
                
        # Load the JSON launcher configuration
        json_launcher_path = config.json_launcher
        logger.info(f"json_launcher: {json_launcher_path}")
        if not json_launcher_path or not os.path.isfile(json_launcher_path):
            raise FileNotFoundError(f"JSON launcher configuration file not found at: {json_launcher_path}")

        with open(json_launcher_path, "r") as json_file:
            json_config = json.load(json_file)

    except Exception as e:
        error_message = f"An error occurred while loading the json file: {e}"
        logger.info(error_message)
        return json.dumps({"error": error_message}), None

    try: 

        # Use either task_info or execution object depending on the received components:
        if (
            not is_file_action
            and not (json_action == "submit_run" or "health-check" in task_id)
        ):
            #If there's no task/tool info provided, use the execution object
            # Extract process_info list from the execution
            process_info_list = execution.get("process_info", [])

            # Find the process_info entry matching the specified node
            task_info = next(
                (info for info in process_info_list if info.get("node") == config.node_name and info.get("task_id") == task_id and info.get("action") == "submit_run"),
                None  # Default value if no match is found
            )

        if not is_file_action and not task_info:
            raise ValueError("Not task_info or execution_info downloaded from DDBB")
        logger.info(f"Task info correctly fetched for {json_action}")
        
    except Exception as e:
        error_message = f"An error occurred while fetching task_info: {e}"
        logger.info(error_message)
        return json.dumps({"error": error_message}), None
    
    # Check if a token_rule command exists in the JSON
    token_rule_cmd = json_config.get("token_rule", {}).get("cmd", {})

    if token_rule_cmd:
        logger.info(f"Found token_rule command, executing to determine which token to use: {token_rule_cmd}")

        try:

            token_cmd = resolve_cmd_placeholders(json_config, "token_rule", token_rule_cmd, argument_values, task_info="")
            new_token = subprocess.run(
                token_cmd,
                shell=True,
                executable="/bin/bash",
                capture_output=True,
                text=True
            )

            if new_token.returncode != 0:
                raise RuntimeError(
                    f"token_rule command failed with code {new_token.returncode}: {new_token.stderr.strip()}"
                )

            token = new_token.stdout.strip()
            argument_values['token'] = token
            logger.info("New token applied")

        except Exception as e:
            error_message = f"Token rule found but failed to be applied: {e}"
            logger.info(error_message)
            return json.dumps({"error": error_message}), None
       
    try:
        # Check if a sandbox_rule command exists in the JSON
        sandbox_rule_cmd = json_config.get("sandbox_rule", {}).get("cmd", {})

        if sandbox_rule_cmd:
            logger.info(f"Found sandbox_rule command, executing to determine SANDBOX_PATH: {sandbox_rule_cmd}")

            sandbox_cmd = resolve_cmd_placeholders(json_config, "sandbox_rule", sandbox_rule_cmd, argument_values, task_info="")
            new_sandbox = subprocess.run(
                sandbox_cmd,
                shell=True,
                executable="/bin/bash",
                capture_output=True,
                text=True
            )

            if new_sandbox.returncode != 0:
                raise RuntimeError(
                    f"sandbox_rule command failed with code {new_sandbox.returncode}: {new_sandbox.stderr.strip()}"
                )

            sandbox_fem = new_sandbox.stdout.strip()
            argument_values['sandbox_fem'] = sandbox_fem
            logger.info(f"Sandbox rule produced path: {sandbox_fem}")

            if not os.path.exists(sandbox_fem):
                raise FileNotFoundError(f"Sandbox path from sandbox_rule does not exist: {sandbox_fem}")

        else:
            # Fallback to using the default SANDBOX_PATH from environment variable
            sandbox_fem = os.getenv("SANDBOX_PATH")
            logger.info(f"No sandbox_rule found; using default SANDBOX_PATH: {sandbox_fem}")

            if not sandbox_fem or not os.path.exists(sandbox_fem):
                raise FileNotFoundError(f"Default SANDBOX_PATH not found or invalid: {sandbox_fem}")

        # Define directories
        # Temporary solution for action that does not need sandbox_path
        if json_action != "list_files":
            user_folder = os.path.join(sandbox_fem, user_id)
            execution_folder = os.path.join(user_folder, execution_id)

            # Check and create directories if they don't exist
            if not os.path.exists(user_folder):
                os.makedirs(user_folder)

            if not os.path.exists(execution_folder):
                os.makedirs(execution_folder)

    except Exception as e:
        error_message = f"Execution folder setup failed: {e}"
        logger.info(error_message)
        return json.dumps({"error": error_message}), None
    
    if "health-check" in task_id:
        # Resolve command to print available docker images
        images_cmd=json_config.get("print_images", {}).get("cmd", {})

        #It won't need task_info or dinamic variables, since it's a system command
        images_cmd = resolve_cmd_placeholders(json_config, "print_images", images_cmd, argument_values, task_info="")

        pre_checks_result = pre_checks(public_ip=public_ip,
                                        images_cmd=images_cmd)

        none_obj = None # empty object to return 2 things, as expected

        return pre_checks_result, none_obj
    
    # Extract command and arguments from the JSON
    # Take into account wheter or not GPUs were detected:
    if json_action == "submit_run":
        gpu_check = check_gpu()
        if gpu_check.get('gpu_detected', False):
            cmd = json_config.get(str(json_action), {}).get("cmd_gpu", {})
        else: 
            cmd = json_config.get(str(json_action), {}).get("cmd", {})
    else:
            cmd = json_config.get(str(json_action), {}).get("cmd", {})
    if not cmd:
        error_message = "Command to run is not defined in the JSON configuration"
        logging.info(error_message)
        return json.dumps({"error": error_message}), None
    
    # Create an execution folder. For docker systems, prepend always "/sandbox"
    # For other systems, prepend the dynamic $sandbox_host
    if isinstance(cmd, list):
        cmd = "\n".join(cmd)
    else:
        cmd = cmd

    cmd_submit = json_config.get("submit_run", {}).get("cmd", {})
    if 'curl -X' in cmd or 'curl -X' in cmd_submit:
        argument_values['sandbox_execution'] = (
            f"{argument_values['sandbox_host']}/%%user_id%%/%%execution_id%%"
        )
    else:
        argument_values['sandbox_execution'] = (
            f"{argument_values['sandbox_fem']}"
        )

    try:

        resolved_cmd = resolve_cmd_placeholders(json_config, json_action, cmd, argument_values, task_info=task_info, parametric_args=parametric_args)
        
        # Run the command
        process = subprocess.run(resolved_cmd, shell=True,  executable="/bin/bash", capture_output=True, text=True)

        stdout = process.stdout.strip()
        stderr = process.stderr.strip()

        if process.returncode != 0:
            logger.error(f"Command failed (rc={process.returncode})")
            if stderr:
                logger.error(stderr)
            if stdout:
                logger.error(f"stdout: {stdout}")

            response = {
                "status": "error",
                "error": stderr,
                "stdout": stdout,
                "returncode": process.returncode
            }

        else:
            logger.info(f"Command executed successfully: {stdout}")

            try:
                json.loads(stdout)
                return stdout, sandbox_fem
            except json.JSONDecodeError as e:
                response = {
                    "status": "error",
                    "error": f"Command returned invalid JSON: {e}",
                    "stdout": stdout,
                    "returncode": 0
                }

        return json.dumps(response), sandbox_fem

    except Exception as e:
        logger.exception("run_tool failed")

        response = {
            "status": "error",
            "error": str(e)
        }

        return json.dumps(response), None
