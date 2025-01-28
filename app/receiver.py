#!/usr/bin/env python
import pika
import json
import os
from dotenv import load_dotenv
import time
import ssl
import logging
from src.commands import *  # Assuming you have commands defined in this module

#read the .env file and load the variables
load_dotenv()

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
        # Extracting tool_id, task_id, execution_id, and user_id from the body
        body_str = body.decode('utf-8')
        components = body_str.split(':')
        logger.info(f'[.] Received command {components}')
        response_message = {} 
        
        #if components[0] == 'None':
        # if len(components) == 4:
        #     logger.info(f'[.] Received command {components}')
        #     file_uri, execution_id, user_id, token = map(str, components)
        #     tool_id = None
        #     task_id = None
        #     logger.info(f'[.] Received command for file_uri: {file_uri}, execution_id: {execution_id}, user_id: {user_id}')

        #     # If it's a file URI, send file bytes
        #     result = send_file_bytes(config.api_base_url, sandbox_path, user_id=user_id, token=token, execution_id=execution_id)
        #     response, command_message = result
        #     response_message = {"response": response, "command_message": command_message}
        #     logger.info(f"RESPONSE: {response}, {command_message}")

        #     # Convert response_message to JSON
        #     response_body = json.dumps(response_message)

        #     # Assuming ch, props are defined elsewhere
        #     ch.basic_publish(
        #         exchange='',
        #         routing_key=props.reply_to,
        #         properties=pika.BasicProperties(correlation_id=props.correlation_id),
        #         body=response_body.encode('utf-8')
        #     )
        #     logger.info(f"[.] Done processing file_uri: {file_uri}, execution_id: {execution_id}, user_id: {user_id}")

        # elif len(components) == 3:
        #     #logger.info(f"components: {components}")
        #     file, execution_id, user_id, token = map(str, components[0:])
        #     folder = execution_id
        #     file_list = list_files(user_id, folder)
        #     response_message = {"response": "success", "file_list": file_list}
        #     logger.info(f"RESPONSE: success, file_list: {file_list}")

        #     # Convert response_message to JSON
        #     response_body = json.dumps(response_message)

        #     # Assuming ch, props are defined elsewhere
        #     ch.basic_publish(
        #         exchange='',
        #         routing_key=props.reply_to,
        #         properties=pika.BasicProperties(correlation_id=props.correlation_id),
        #         body=response_body.encode('utf-8')
        #     )
        #     logger.info(f"[.] Done processing folder: {folder}, execution_id: {execution_id}, user_id: {user_id}")

        if len(components) == 5:
            task_id, execution_id, user_id, token, json_action = map(str, components)
            logger.info(f'[.] Received {json_action} command for execution_id: {execution_id}, user_id: {user_id}')

            result = run_tool(api_base_url=config.api_base_url, task_id=task_id, execution_id=execution_id, user_id=user_id, token=token, json_action=json_action)
            if isinstance(result, tuple):
                response, command_message = result
            else:
                response = result
                command_message = None

            response_message = {"response": response, "command_message": command_message}
            logger.info(f"{json_action} RESPONSE: {response}, {command_message}")
 
        elif len(components) == 6 and components[0] != "None":
            tool_id, task_id, execution_id, user_id, token, json_action = map(str, components)
            logger.info(f'[.] Received {json_action} command for tool_id: {tool_id}, task_id: {task_id}, execution_id: {execution_id}, user_id: {user_id}')

            result = run_tool(api_base_url=config.api_base_url, task_id=task_id, execution_id=execution_id, user_id=user_id, token=token, json_action=json_action)
            if isinstance(result, tuple):
                response, command_message = result
            else:
                response = result
                command_message = None

            response_message = {"response": response, "command_message": command_message}
            logger.info(f"RESPONSE: {response}, {command_message}")

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
