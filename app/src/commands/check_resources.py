import subprocess
import os
import psutil
import socket
import logging
from pathlib import Path
import json

# Set up logging configuration
#logging.basicConfig(filename='receiver.log', level=logging.INFO)

def check_installations():
    try:
        command = "docker --version; curl -s ipinfo.io"
        logging.info(f'EXECUTING COMMAND: {command}')
        check = subprocess.run(command, shell=True, capture_output=True, text=True)
        response = check.stdout.strip()

        # Try parsing the second command output as JSON
        parts = response.split("\n", 1)
        docker_version = parts[0] if parts else "Unknown"
        ip_info = {}
        
        if len(parts) > 1:
            try:
                ip_info = json.loads(parts[1])  # Attempt to parse IP info as JSON
            except json.JSONDecodeError:
                ip_info = {"error": "Failed to parse IP info"}

        return {
            "docker_version": docker_version,
            "ip_info": ip_info
        }
    
    except Exception as e:
        logging.error(f"Error calling Docker. Traceback: {e}")
        return {"error": str(e)}

def check_gpu():
    try:
        subprocess.check_output('nvidia-smi', stderr=subprocess.STDOUT, shell=True)
        logging.info('Nvidia GPU detected')
        return {"gpu_detected": True, "message": "Nvidia GPU detected"}
    except subprocess.CalledProcessError as e:
        logging.warning(f'No Nvidia GPU in the system. Traceback: {e}')
        return {"gpu_detected": False, "message": "No Nvidia GPU in the system"}

def check_paths():
    sandbox_path = Path("/app/sandbox")
    data_path = Path("/app/data")

    paths_status = {
        "sandbox_path_exists": sandbox_path.exists(),
        "data_path_exists": data_path.exists(),
        "sandbox_contents": [],
        "data_path_contents": []
    }

    if sandbox_path.exists():
        paths_status["sandbox_contents"] = os.listdir(sandbox_path)

    if data_path.exists():
        paths_status["data_path_contents"] = os.listdir(data_path)

    return paths_status

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
        host = socket.gethostbyname("www.google.com")
        socket.create_connection((host, 80), 2)
        has_internet = True
    except:
        has_internet = False

    resources = {
        "CPU Count": cpu_count,
        "CPU Percent": cpu_percent,
        "Memory Available": f"{memory_available / (1024 ** 3):.2f} GB",
        "Memory Total": f"{memory_total / (1024 ** 3):.2f} GB",
        "GPU Count": gpu_count,
        "Has Internet": has_internet,
    }

    if check == "all":
        return resources

    filtered_resources = {}
    if check == "cpu":
        filtered_resources["cpu_count"] = cpu_count
        filtered_resources["cpu_percent"] = cpu_percent
    elif check == "memory":
        filtered_resources["memory_available_gb"] = round(memory_available / (1024 ** 3), 2)
        filtered_resources["memory_total_gb"] = round(memory_total / (1024 ** 3), 2)
    elif check == "gpu":
        filtered_resources["gpu_count"] = gpu_count
    elif check == "internet":
        filtered_resources["has_internet"] = has_internet
    else:
        raise ValueError(f"Invalid argument {check}, use all, cpu, memory, gpu, or internet")

    return filtered_resources


def pre_checks():
    logging.info("Running all pre-checks...")

    results = {
        "installation_check": check_installations(),
        "gpu_check": check_gpu(),
        "paths_check": check_paths(),
        "resources_check": check_resources("all")
    }

    # Log the summary for reference
    #logging.info("RESPONSE:\n%s", result_summary)

    return json.dumps(results)



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



