import json
import subprocess
import os
import psutil
import socket
import logging
from pathlib import Path
from config import config

# Set up logging configuration
logging.basicConfig(filename='receiver.log', level=logging.INFO)

def check_installations():
    try:
        command = "docker --version; curl ipinfo.io"
        logging.info(f'EXECUTING COMMAND: {command}')
        check = subprocess.run(command, shell=True, capture_output=True)
        response = check.stdout.decode()
        logging.info(response)
        return response
    except Exception as e:
        logging.error(f"Error calling Docker. If the user running the bash script is not part of the docker group, please add it with the following commands: 1) `sudo groupadd docker`, 2)`sudo usermod -aG docker $USER`, 3)`newgrp docker`.\nTraceback: {e}")
        return str(e)

def check_gpu():
    try:
        check = subprocess.check_output('nvidia-smi')
        response = 'Nvidia GPU detected'
        logging.info('Nvidia GPU detected')
        return response
    except Exception as e:
        logging.warning(f'No Nvidia GPU in the system.\nTraceback: {e}')
        response = 'No Nvidia GPU in the system'
        return response

def check_paths():
    sandbox_path = Path(config.sandbox_path)
    data_path = Path(config.data_path)
    response = ""

    if not data_path.exists():
        logging.error(f"Data path does not exist or is not set: {data_path}")
        response += f"Data path does not exist or is not set: {data_path}\n"
    # else:
    #     # List the contents of the data path
    #     data_contents = subprocess.run(['ls', '-l', str(data_path)], capture_output=True, text=True)
    #     logging.info(f"Data path contents:\n{data_contents.stdout}")
    #     response += f"Data path contents:\n{data_contents.stdout}\n"

    if not sandbox_path.exists():
        logging.error(f"Sandbox path does not exist or is not set: {sandbox_path}")
        response += f"Sandbox path does not exist or is not set: {sandbox_path}\n"

    else:
        sandbox_contents = os.listdir(sandbox_path)
        logging.info(f"Sandbox path contents:\n{sandbox_contents}")
        response += f"Sandbox path contents:\n{sandbox_contents}\n"

    if response == "":
        logging.info("Paths are valid")
        response = "Paths are valid"

    return response


def check_resources(check):
    cpu_count = psutil.cpu_count()
    cpu_percent = psutil.cpu_percent()
    virtual_memory = psutil.virtual_memory()
    memory_available = virtual_memory.available
    memory_total = virtual_memory.total

    try:
        import GPUtil
        gpu_count = len(GPUtil.getGPUs())
    except ImportError:
        gpu_count = 0

    try:
        # connecting to a website that always exists
        host = socket.gethostbyname("www.google.com")
        socket.create_connection((host, 80), 2)
        has_internet = True
    except:
        has_internet = False

    resources = {
        'CPU Count': cpu_count,
        'CPU Percent': cpu_percent,
        'Memory Available': f"{memory_available / (1024 ** 3):.2f} GB",
        'Memory Total': f"{memory_total / (1024 ** 3):.2f} GB",
        'GPU Count': gpu_count,
        'Has Internet': has_internet,
    }

    if check == 'all':
        return resources

    result = {}
    if check == 'cpu':
        result['CPU Count'] = cpu_count
        result['CPU Percent'] = cpu_percent
    elif check == 'memory':
        result['Memory Available'] = f"{memory_available / (1024 ** 3):.2f} GB"
        result['Memory Total'] = f"{memory_total / (1024 ** 3):.2f} GB"
    elif check == 'gpu':
        result['GPU Count'] = gpu_count
    elif check == 'internet':
        result['Has Internet'] = has_internet
    else:
        raise ValueError(f"Invalid argument {check}, use all, cpu, memory, gpu, or internet")

    return result


def pre_checks():
    logging.info("Running all pre-checks...")

    installations_result = check_installations()
    gpu_result = check_gpu()
    paths_result = check_paths()
    resources_result = check_resources('all')

    # Create a formatted string with clear section headers and consistent indentation
    result_summary = (
        "Installation Check:\n"
        f"{installations_result}\n\n"
        "GPU Check:\n"
        f"{gpu_result}\n\n"
        "Paths Check:\n"
        f"{paths_result}\n\n"
        "Resources Check:\n"
        f"{resources_result}\n"
    )

    # Log the summary for reference
    logging.info("RESPONSE:\n%s", result_summary)

    return result_summary



if __name__ == '__main__':
    # Get arguments from the command line using argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--function", help="function to execute (pre_checks, check_installations, check_gpu, check_paths, check_resources)", type=str, default='check_resources')
    parser.add_argument("--argument", help="check type (cpu, memory, gpu, internet)", type=str, default='all')

    args = parser.parse_args()

    if args.function == 'pre_checks':
        pre_checks()
    elif args.function == 'check_installations':
        check_installations()
    elif args.function == 'check_gpu':
        check_gpu()
    elif args.function == 'check_paths':
        check_paths()
    elif args.function == 'check_resources':
        check_resources(args.argument)
    else:
        logging.error("Invalid function specified.")



