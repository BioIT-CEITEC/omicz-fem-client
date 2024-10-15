import json
import os
import argparse
import logging
import time
from .launcher import * 
from .utils import *
from .data_operations import *
from .check_resources import *
from config import config
import requests

def fetch_tool_info(api_base_url, tool_id):
    try:
        # Make a request to the endpoint to get the tool information
        #response = requests.get(f"https://fl.bsc.es/flmanager/API/v1/tools/{tool_id}")
        response = requests.get(f"{api_base_url}/tools/{tool_id}")
        tool_info = response.json()
        return tool_info
    except Exception as e:
        print(f"Error fetching tool information: {e}")
        return None


def run_tool(api_base_url, task_id, execution_id, user_id=None):
    try:
        logger = logging.getLogger("receiver")

        # Perform pre-checks if specified in the tool entry
        tool_info = fetch_tool_info(task_id)
        if tool_info:
            pre_checks_result = pre_checks()
            #logger.info(f"Pre-checks result: {pre_checks_result}")

            # Determine the launcher type
            launcher_type = tool_info.get("info_from_tasks_collection", {}).get("launcher", "")
            if isinstance(launcher_type, list) and launcher_type:
                launcher_type = launcher_type[0]

            if launcher_type.lower() == "docker":
                launcher = DockerLauncher(tool_info, task_id, execution_id, logger=logger, user_id=user_id)
                container_id = launcher.start_tool()
                config_dir = os.path.join(config.sandbox_path, "config", task_id)
                os.makedirs(config_dir, exist_ok=True)
                if container_id:
                    time.sleep(5)  
                    generated_files = os.listdir(os.path.join(config.sandbox_path, user_id, execution_id))
                    logger.info(f"Tool started successfully for task_id: {task_id}")
                    logger.info(f"Container ID: {container_id}")

                    send_generated_files(api_base_url, generated_files, task_id, user_id, execution_id)
                    return container_id, generated_files
                else:
                    return f"Error starting tool for task_id: {task_id}"
            elif launcher_type.lower() == "generic":
                launcher = GenericLauncher(tool_info, task_id, execution_id, logger=logger, user_id=user_id)
                logger.info(f"Generic launcher called for {tool_info}")
                response = launcher.start_tool()
                return response
            else:
                #logger.info(f"launcher: {launcher_type}")
                return pre_checks_result

            # Start the tool using the appropriate launcher
            container_id = launcher.start_tool()
            config_dir = os.path.join(config.sandbox_path, "config", task_id)
            os.makedirs(config_dir, exist_ok=True)
            if container_id:
                time.sleep(5)  
                generated_files = os.listdir(os.path.join(config.sandbox_path, user_id, execution_id))
                logger.info(f"Tool started successfully for task_id: {task_id}")
                logger.info(f"Container ID: {container_id}")

                send_generated_files(api_base_url, generated_files, task_id, user_id, execution_id)
                return container_id, generated_files
            else:
                return f"Error starting tool for task_id: {task_id}"
        else:
            return f"Error fetching tool information for task_id: {task_id}"
    except Exception as e:
        return f"Error occurred: {e}"


if __name__ == '__main__': # TODO Decide whether to keep command line usage, needs to read config
    parser = argparse.ArgumentParser()
    parser.add_argument("--task_id", help="ID of the task to run", type=str)
    parser.add_argument("--user_id", help="User ID", type=str)
    args = parser.parse_args()
    
    
    logging.basicConfig(level=logging.INFO)
    
    logger = logging.getLogger(__name__)
    logger.info(f"Running tool for task_id: {args.task_id}")
    
    run_tool(args.task_id, args.user_id)
