import subprocess
import os
import psutil
import logging
from pathlib import Path
import json
import datetime
import GPUtil
import requests
from config import config

# Set up logging configuration
#logging.basicConfig(filename='receiver.log', level=logging.INFO)

def docker_version():
    try:
        # Check Docker version
        command = "docker --version"
        check = subprocess.run(command, shell=True, capture_output=True, text=True)
        docker_version = check.stdout.strip() or "Unknown"

        return docker_version

    except Exception as e:
        logging.error(f"Error checking installations. Traceback: {e}")
        return {"error": str(e)}

def check_gpu():
    try:
        subprocess.check_output('nvidia-smi', stderr=subprocess.STDOUT, shell=True)
        logging.info('Nvidia GPU detected')
        return {"gpu_detected": True, "message": "Nvidia GPU detected"}
    except Exception as e:
        logging.warning(f'No Nvidia GPU in the system or nvidia-smi failed. Error: {e}')
        return {"gpu_detected": False, "message": "No Nvidia GPU or driver error"}

def check_paths():
    """Health-check view of the node's storage.

    The sandbox is a real mount and is probed. The datasets are not: they are mounted by
    the WES workers, so `/data` does not exist in this container and the health check
    answers from `config.datasets` — the same declaration `list_files /data` serves. The
    field names are the orchestrator's and stay as they are.
    """
    sandbox_path = Path(os.environ.get('SANDBOX_PATH', '/sandbox'))
    datasets = getattr(config, "datasets", None) or {}

    paths_status = {
        "sandbox_path_exists": sandbox_path.exists(),
        "data_path_exists": bool(datasets),
        "sandbox_contents": [],
        "data_path_contents": sorted(datasets),
    }

    if sandbox_path.exists():
        paths_status["sandbox_contents"] = os.listdir(sandbox_path)

    return paths_status

def check_resources(check):
    cpu_count = psutil.cpu_count()
    cpu_percent = psutil.cpu_percent()
    virtual_memory = psutil.virtual_memory()
    memory_available = virtual_memory.available
    memory_total = virtual_memory.total

    try:
        gpu_count = len(GPUtil.getGPUs())
    except Exception as e:
        logging.warning(f'GPUtil failed to get GPUs: {e}')
        gpu_count = 0

    try:
        response = requests.get("https://fl.bsc.es/dt4h-fem/API/v1/docs", timeout=2)
        has_internet = response.status_code == 200
    except Exception as e:
        logging.warning(f'Internet check via API failed: {e}')
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

def check_docker_images(images_cmd):
    try:
        command = images_cmd
        result = subprocess.run(command, shell=True, capture_output=True, text=True)

        return {"docker_images": json.loads(result.stdout.strip())}
    
    except Exception as e:
        return {"error": str(e)}
    
def check_pem_expiry(rabbitmq_folder):
    pem_files = [f for f in os.listdir(rabbitmq_folder) if f.endswith(".pem")]
    cert_expirations = {}

    for pem_file in pem_files:
        pem_path = os.path.join(rabbitmq_folder, pem_file)

        try:
            # Identify if file is a certificate
            with open(pem_path, "r") as f:
                content = f.read()
                if "BEGIN CERTIFICATE" not in content:
                    # Skip if not a certificate
                    continue

            # Run OpenSSL command to get expiration date
            command = f"openssl x509 -enddate -noout -in \"{pem_path}\""
            result = subprocess.run(command, shell=True, capture_output=True, text=True)
            output = result.stdout.strip()

            if "notAfter=" in output:
                expiry_date_str = output.split("=")[1]
                try:
                    expiry_date = datetime.datetime.strptime(expiry_date_str, "%b %d %H:%M:%S %Y %Z")
                except ValueError:
                    # Handle if timezone is not included
                    expiry_date = datetime.datetime.strptime(expiry_date_str, "%b %d %H:%M:%S %Y")
                
                is_expired = expiry_date < datetime.datetime.utcnow()
                cert_expirations[pem_file] = {
                    "expiry_date": expiry_date.strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "status": "Expired" if is_expired else "Valid"
                }

        except Exception as e:
            # Only show error if the file is a cert and fails to parse
            cert_expirations[pem_file] = {"error": str(e)}

    return cert_expirations



def pre_checks(images_cmd, public_ip=None):
    logging.info("Running all pre-checks...")

    results = {
        "docker_version": docker_version(),
        "public_ip": public_ip,
        "gpu_check": check_gpu(),
        "paths_check": check_paths(),
        "resources_check": check_resources("all"),
        "docker_images_installed": check_docker_images(images_cmd),
        "pem_certificates": check_pem_expiry('/app/config/rabbitmq-certificates') 
    }

    # Log the summary for reference
    #logging.info("RESPONSE:\n%s", result_summary)

    return json.dumps(results)




