import subprocess
import os
import psutil
import socket
import logging
from pathlib import Path
import json
import datetime
import GPUtil

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
    except Exception as e:
        logging.warning(f'No Nvidia GPU in the system or nvidia-smi failed. Error: {e}')
        return {"gpu_detected": False, "message": "No Nvidia GPU or driver error"}

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
        gpu_count = len(GPUtil.getGPUs())
    except Exception as e:
        logging.warning(f'GPUtil failed to get GPUs: {e}')
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

def check_docker_images():
    try:
        command = "docker images --digests --format '{{json .}}'"
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        lines = result.stdout.strip().split("\n")

        images = []
        for line in lines:
            if line.strip():
                image_info = json.loads(line)
                images.append({
                    "repository": image_info.get("Repository", "<none>"),
                    "tag": image_info.get("Tag", "<none>"),
                    "image_id": image_info.get("ID", "Unknown"),
                    "sha256_digest": image_info.get("Digest", "Unknown")
                })

        return {"docker_images": images}
    
    except Exception as e:
        return {"error": str(e)}
    
def check_pem_expiry(rabbitmq_folder):
    pem_files = [f for f in os.listdir(rabbitmq_folder) if f.endswith(".pem")]
    cert_expirations = {}

    for pem_file in pem_files:
        pem_path = os.path.join(rabbitmq_folder, pem_file)
        try:
            # Run OpenSSL command to get expiration date
            command = f"openssl x509 -enddate -noout -in {pem_path}"
            result = subprocess.run(command, shell=True, capture_output=True, text=True)
            output = result.stdout.strip()

            if "notAfter=" in output:
                expiry_date_str = output.split("=")[1]
                expiry_date = datetime.datetime.strptime(expiry_date_str, "%b %d %H:%M:%S %Y %Z")
                
                # Check if expired
                is_expired = expiry_date < datetime.datetime.utcnow()
                cert_expirations[pem_file] = {
                    "expiry_date": expiry_date.strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "status": "Expired" if is_expired else "Valid"
                }
            else:
                cert_expirations[pem_file] = {"error": "Unable to retrieve expiration date"}
        
        except Exception as e:
            cert_expirations[pem_file] = {"error": str(e)}

    return cert_expirations


def pre_checks():
    logging.info("Running all pre-checks...")

    results = {
        "installation_check": check_installations(),
        "gpu_check": check_gpu(),
        "paths_check": check_paths(),
        "resources_check": check_resources("all"),
        "docker_images_installed": check_docker_images(),
        "pem_certificates": check_pem_expiry('/app/config/rabbitmq-certificates') 
    }

    # Log the summary for reference
    #logging.info("RESPONSE:\n%s", result_summary)

    return json.dumps(results)




