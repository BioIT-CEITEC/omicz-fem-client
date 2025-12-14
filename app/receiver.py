#!/usr/bin/env python
import pika
import json
import os
import ssl
import logging
from services.check_resources import *
from services.run_tool import *
from services.data_operations import *
from services.utils import *
from config import config
from dotenv import load_dotenv
import threading
import time
from threading import Lock
import hashlib
import math
import base64

CHUNK_SIZE = 120000

def compute_checksum(binary_data):
    return hashlib.sha256(binary_data).hexdigest()

def chunk_generator(data_bytes, chunk_size=CHUNK_SIZE):
    """
    Yield base64-encoded chunks from raw bytes.
    Used by send_response for non-file messages.
    """
    import base64
    for i in range(0, len(data_bytes), 3 * (chunk_size // 4)):
        chunk = data_bytes[i:i + 3 * (chunk_size // 4)]
        yield base64.b64encode(chunk).decode("utf-8")


def send_response(ch, routing_key, correlation_id, response_bytes, logger):
    """
    Streams response_bytes in chunks progressively to RabbitMQ.
    Total chunks calculated without pre-encoding entire response.
    """
    checksum = compute_checksum(response_bytes)
    total_bytes = len(response_bytes)

    # Compute total_chunks from bytes length
    encoded_length = 4 * math.ceil(total_bytes / 3)
    total_chunks = max(1, math.ceil(encoded_length / CHUNK_SIZE))

    # Send chunk_start first
    ch.basic_publish(
        exchange='',
        routing_key=routing_key,
        properties=pika.BasicProperties(correlation_id=correlation_id),
        body=json.dumps({
            "type": "chunk_start",
            "total": total_chunks,
            "checksum": checksum
        }).encode()
    )
    logger.info(f"[.] Sent chunk_start for {total_chunks} chunks")

    # Stream chunks
    for i, chunk in enumerate(chunk_generator(response_bytes)):
        ch.basic_publish(
            exchange='',
            routing_key=routing_key,
            properties=pika.BasicProperties(correlation_id=correlation_id),
            body=json.dumps({
                "type": "chunk",
                "index": i,
                "data": chunk
            }).encode()
        )
        logger.info(f"[.] Sent chunk {i+1}/{total_chunks}")

        # Flush immediately
        if hasattr(ch.connection, "process_data_events"):
            ch.connection.process_data_events()



# Execution sandbox map: execution_id -> (sandbox_path, expiry_timestamp)
execution_sandboxes = {}
execution_sandboxes_lock = Lock()

# How long to keep a sandbox mapping after last set (seconds).
# Set to whatever makes sense; e.g. 3600 = 1 hour
EXECUTION_SANDBOX_TTL = 300

#read the .env file and load the variables
load_dotenv()

# Function to setup logger
def setup_logger():
    logger = logging.getLogger("receiver")
    logger.setLevel(logging.DEBUG)

    log_file = os.getenv("LOG_FILE")
    fh = logging.FileHandler(log_file)
    fh.setLevel(logging.DEBUG)

    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)

    formatter = logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)

    logger.addHandler(fh)
    logger.addHandler(ch)

    # Set up logging for the requests library
    logging.getLogger("requests").setLevel(logging.DEBUG)
    logging.getLogger("urllib3").setLevel(logging.DEBUG)

    logger.propagate = False

    return logger

# Functions to store DYNAMIC SANDBOX in the env during executions:
def set_execution_sandbox(execution_id: str, sandbox_path: str, ttl: int = EXECUTION_SANDBOX_TTL):
    """Store sandbox for an execution id with expiry."""
    expiry = time.time() + ttl
    with execution_sandboxes_lock:
        execution_sandboxes[str(execution_id)] = (sandbox_path, expiry)

def get_execution_sandbox(execution_id: str):
    """Return sandbox_path for execution_id or None if not set/expired."""
    with execution_sandboxes_lock:
        entry = execution_sandboxes.get(execution_id)
        if not entry:
            return None
        sandbox_path, expiry = entry
        if time.time() > expiry:
            # expired → remove
            del execution_sandboxes[execution_id]
            return None
        return sandbox_path

def clear_execution_sandbox(execution_id: str):
    """Remove mapping for an execution_id immediately."""
    with execution_sandboxes_lock:
        execution_sandboxes.pop(execution_id, None)

def _execution_sandbox_cleanup_worker():
    """Daemon thread to remove expired entries periodically."""
    while True:
        now = time.time()
        with execution_sandboxes_lock:
            expired = [k for k, (_, exp) in execution_sandboxes.items() if exp < now]
            for k in expired:
                del execution_sandboxes[k]
        time.sleep(60)  # check every minute

# start background thread once
cleanup_thread = threading.Thread(target=_execution_sandbox_cleanup_worker, daemon=True)
cleanup_thread.start()

# Function to handle incoming requests
def on_request(ch, method, props, body, logger):
    logger.info("[.] Received a message")

    try:
        try:
            packet = json.loads(body.decode('utf-8'))
        except Exception:
            packet = None

        if packet and packet.get("type") == "chunk_start":
            # Initialize chunk reception
            logger.info("[.] Start of incoming chunked command")
            ch._chunks = {}
            ch._total_chunks = packet["total"]
            ch._checksum = packet["checksum"]
            ch.basic_ack(delivery_tag=method.delivery_tag)
            return

        if packet and packet.get("type") == "chunk":
            if not hasattr(ch, "_chunks"):
                logger.warning("Chunk received without chunk_start, initializing anyway")
                ch._chunks = {}
                ch._total_chunks = packet.get("total", 0)
                ch._checksum = packet.get("checksum", None)

            # Store chunk
            idx = packet["index"]
            ch._chunks[idx] = packet["data"]

            if len(ch._chunks) < ch._total_chunks:
                ch.basic_ack(delivery_tag=method.delivery_tag)
                return

            # Reassemble all chunks
            logger.info("[.] All chunks received, reassembling command")
            full_b64 = "".join(ch._chunks[i] for i in sorted(ch._chunks))
            binary = base64.b64decode(full_b64)

            if compute_checksum(binary) != ch._checksum:
                logger.error("Checksum mismatch in command")
                ch.basic_ack(delivery_tag=method.delivery_tag)
                return

            body_bytes = binary

        else:
            # Fallback for non-chunked (small) messages
            body_bytes = body

        # --- Convert bytes to string for orchestrator → client commands ---
        try:
            body_str = body_bytes.decode('utf-8')
        except Exception:
            body_str = None  # keep as bytes if not UTF-8

        components = []

        if body_str is not None:
            # Always split string commands
            if "|" in body_str:
                parts = body_str.split("|")

                # Convert literal `"None"` into real Python None
                components = [None if (isinstance(p, str) and p.strip("'\"") == "None") else p for p in parts]
                logger.info(f"[.] Received command: {components}")
            else:
                components = [body_str]  # single command without "|"
        else:
            # Not UTF-8 → keep as bytes
            components = [body_bytes]

        response_message = {}

        if components[0] == "other_tasks":
            task_info, execution, user_id, json_action, token = components[1:6]
            logger.info(f'[.] Received {json_action} command for execution_id: {execution}, user_id: {user_id}')

            result, sandbox_path = run_tool(task_info=task_info, 
                              execution=execution, 
                              parametric_args=None,
                              user_id=user_id, 
                              public_ip=None,
                              json_action=json_action, 
                              token = token)
            
            response_message = json.loads(result)
            logger.info(f"{json_action} RESPONSE: {response_message}")

        elif components[0] == "submit_run":
            tool_id, task_info, execution, parametric_args, user_id, public_ip, json_action, token = components[1:9]
            task_id = {re.search(r"'_id'\s*:\s*'([^']+)'", task_info)}
            #Convert the parametric_args variable into a dictionary
            parametric_args = eval(parametric_args)
            logger.info(f'[.] Received {json_action} command for tool_id: {tool_id}, task_id: {task_id}, user_id: {user_id}')

            result, sandbox_path = run_tool(task_info=task_info, 
                              execution=execution, 
                              parametric_args=parametric_args,
                              user_id=user_id, 
                              public_ip = public_ip,
                              json_action=json_action,
                              token = token)
            
            # New logic to save dynamic $SANDBOX_PATH to execution env
            try:
                response_message = json.loads(result)
            except Exception:
                logger.exception("run_tool did not return valid JSON")
                result = {"status": "error", "raw_result": result}

            # If submit_run provided a sandbox_path, store it for the execution
            if json_action == "submit_run" and sandbox_path:
                logger.info(f"Storing sandbox for execution {execution}: {sandbox_path}")
                execution = json.loads(execution)
                execution_id = execution.get('execution_id')
                set_execution_sandbox(execution_id, sandbox_path)

            logger.info(f"RESPONSE: {response_message}")
 
        elif components[0] == "list_files":
            user_id, execution_id, path = components[1:4]
            sandbox_base = get_execution_sandbox(execution_id) or os.environ.get("SANDBOX_PATH", "/sandbox")

            logger.info(f'[.] Received list_files command for path: {path}')

            response_message = list_files(user_id=user_id,
                                execution_id=execution_id,
                                path=path,
                                sandbox_base = sandbox_base)
            
            #response_message = json.loads(result)
            logger.info(f"list_files RESPONSE: {response_message}")

        elif components[0] == "send_files":
            user_id, execution_id, file, sandbox_base = components[1:5]

            logger.info(f'[.] Received send_files command for execution_id: {execution_id}')

            response_message = send_files_as_json(user_id = user_id, 
                                                  execution_id = execution_id, 
                                                  file = file,
                                                  sandbox_base = sandbox_base)

            logger.info(f"send_files RESPONSE: {response_message}")


        elif components[0] == "receive_files":
            user_id, execution_id, incoming_files = components[1:4]
            sandbox_base = get_execution_sandbox(execution_id) or os.environ.get("SANDBOX_PATH", "/sandbox")

            logger.info(f'[.] Received receive_files command for execution_id: {execution_id}')

            response_message = receive_files(user_id = user_id,
                                              execution_id = execution_id,
                                              incoming_files = incoming_files,
                                              sandbox_base = sandbox_base)

            logger.info(f"receive_files RESPONSE: {response_message}")


        else:
            logger.error(f"Invalid body format. Expected 3 or 4 components separated by colons, but received: {body_str}")
            ch.basic_ack(delivery_tag=method.delivery_tag)
            return

        # Send response message back, chunked if necessary:
        response_bytes = json.dumps(response_message).encode('utf-8')
        send_response(ch, props.reply_to, props.correlation_id, response_bytes, logger)
        ch.basic_ack(delivery_tag=method.delivery_tag)

        logger.info("[.] Done processing request")

    except Exception as ex:
        logger.error("Exception in on_request: %s", ex)
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    finally:
        logger.info("[.] Awaiting for requests")


def run_receiver():
    logger = setup_logger()
    logger.info(f"[.] Receiver process ID: {os.getpid()}")

    try:
        if config.ssl_active:
            context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
            context.check_hostname = False
            context.load_verify_locations(cafile=config.ssl_cafile_path)
            context.load_cert_chain(certfile=config.ssl_client_cert_path, keyfile=config.ssl_client_keys_path)
            ssl_options = pika.SSLOptions(context, config.central_server_ip)
            credentials = pika.PlainCredentials(config.node_user, config.node_password)
            params = pika.ConnectionParameters(host=config.central_server_ip, port=config.ssl_central_server_port,
                                               virtual_host=config.central_rabbitmq_vhost, ssl_options=ssl_options,
                                               credentials=credentials)
        else:
            credentials = pika.PlainCredentials(config.node_user, config.node_password)
            params = pika.ConnectionParameters(host=config.central_server_ip, port=config.ssl_central_server_port,
                                               virtual_host=config.central_rabbitmq_vhost, heartbeat=600,
                                               blocked_connection_timeout=300, credentials=credentials)

        logger.info(f"[.] RabbitMQ params: {params}")
        connection = pika.BlockingConnection(params)
        channel = connection.channel()
        # Enable publisher confirms
        channel.confirm_delivery()

        channel.queue_declare(queue=config.node_name)

        channel.basic_qos(prefetch_count=1)
        channel.basic_consume(queue=config.node_name, on_message_callback=lambda ch, method, props, body: on_request(ch, method, props, body, logger))
        logger.info("[.] Awaiting for requests")
        channel.start_consuming()

    except pika.exceptions.StreamLostError as e:
        logger.error("SSL connection lost. Reconnecting...")
        time.sleep(5)
        run_receiver()

    except Exception as e:
        logger.exception("Error occurred while running receiver")


if __name__ == "__main__":
    run_receiver()
