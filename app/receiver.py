#!/usr/bin/env python
import pika
import json
import os
import time
import ssl
import logging
from services.check_resources import *
from services.run_tool import *
from services.data_operations import *
from services.utils import *


# Function to load configuration
def load_configuration():
    try:
        import config.config as config
        return config
    except ImportError:
        raise ImportError("Configuration file not found or has an invalid format.")
    except Exception as e:
        raise RuntimeError(f"Error loading configuration: {e}")

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

# Function to handle incoming requests
def on_request(ch, method, props, body, logger):
    logger.info("[.] Received a message")
    config = load_configuration()

    try:
        # Extracting components from the body
        body_str = body.decode('utf-8')
        components = body_str.split('|')
        components = [None if (isinstance(c, str) and c.strip("'\"") == "None") else c for c in components]
        logger.info(f'[.] Received command {components}')
        response_message = {} 
        
        if len(components) == 4:
            task_info, execution, user_id, json_action = components
            logger.info(f'[.] Received {json_action} command for execution_id: {execution}, user_id: {user_id}')

            result = run_tool(task_info=task_info, 
                              execution=execution, 
                              parametric_args=None,
                              user_id=user_id, 
                              public_ip=None,
                              json_action=json_action)
            
            response_message = json.loads(result)
            logger.info(f"{json_action} RESPONSE: {response_message}")
 
        elif len(components) == 7 and components[0] != "None":
            tool_id, task_info, execution, parametric_args, user_id, public_ip, json_action = components
            task_id = {re.search(r"'_id'\s*:\s*'([^']+)'", task_info)}
            #Convert the parametric_args variable into a dictionary
            parametric_args = eval(parametric_args)
            logger.info(f'[.] Received {json_action} command for tool_id: {tool_id}, task_id: {task_id}, user_id: {user_id}')

            result = run_tool(task_info=task_info, 
                              execution=execution, 
                              parametric_args=parametric_args,
                              user_id=user_id, 
                              public_ip = public_ip,
                              json_action=json_action)
            
            response_message = json.loads(result)
            logger.info(f"RESPONSE: {response_message}")
 
        elif components[0] == "list_files":
            container_id, path = components[1:3]
            logger.info(f'[.] Received list_files command for path: {path}, container: {container_id}')

            response_message = list_files(container_id=container_id,
                                path=path)
            
            #response_message = json.loads(result)
            logger.info(f"list_files RESPONSE: {response_message}")

        elif components[0] == "send_files":
            user_id, execution_id, file = components[1:4]
            logger.info(f'[.] Received send_files command for execution_id: {execution_id}')

            response_message = send_files_as_json(user_id = user_id, 
                                                  execution_id = execution_id, 
                                                  file = file)
            
            logger.info(f"list_files RESPONSE: {response_message}")

        else:
            logger.error(f"Invalid body format. Expected 3 or 4 components separated by colons, but received: {body_str}")
            return

        response_body = json.dumps(response_message)
        ch.basic_publish(
            exchange='',
            routing_key=props.reply_to,
            properties=pika.BasicProperties(correlation_id=props.correlation_id),
            body=response_body.encode('utf-8')
        )
        logger.info("[.] Done processing request")

    except Exception as ex:
        logger.error("Exception in on_request: %s", ex)
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    finally:
        ch.basic_ack(delivery_tag=method.delivery_tag)
        logger.info("[.] Awaiting for requests")


def run_receiver():
    logger = setup_logger()
    logger.info(f"[.] Receiver process ID: {os.getpid()}")

    config = load_configuration()

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
