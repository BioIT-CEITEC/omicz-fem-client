#!/usr/bin/env python
import os

# ----------------------------------------------------------------
# IMPORTANT NOTES TO DEVELOPERS
# 1 - MAKE A COPY OF THIS FILE AND REMOVE THE "_template" PART
# 2 - THE .GITIGNORE INCLUDES A PATTERN TO NOT COMMIT THIS FILE, 
# BUT MAKE SURE IT DOES NOT GET INCLUDED IN ANY OF YOUR COMMITS
# ----------------------------------------------------------------

# ----------------------------------------------------------------
# REPLACE THE FOLLOWING VARIABLES WITH YOUR OWN
# ----------------------------------------------------------------
node_name = 'YourNodeName'
# node_name can be "OX", "UB", "BUCH", "GEM", "ICRC", "KUH", "UCL", "UMCU", "AUMC", "VHIR",

data_path = '/path/to/your/data'
sandbox_path = '/path/to/your/sandbox'
node_user = 'your_node_user'
node_password = 'your_node_password'
cert_phrase = 'your_cert_passphrase'

# ----------------------------------------------------------------
# REPLACE THE FOLLOWING VARIABLES WITH YOUR OWN
# ----------------------------------------------------------------
ssl_active = True
ssl_central_server_port = 5671
ssl_cafile_path = '/path/to/your/cafile/rootCA_cert.pem'
ssl_client_cert_path = '/path/to/your/client_cert/client_cert.pem'
ssl_client_keys_path = '/path/to/your/client_keys/client_key.pem'

# ----------------------------------------------------------------
# KEEP THE FOLLOWING VARIABLES WITH THE PROJECT'S VALUES
# ----------------------------------------------------------------
central_server_ip = 'fl.bsc.es'
central_server_port = 5671
central_rabbitmq_vhost = 'rabbit_server'
api_base_url = '/flmanager/API/v1'

# ----------------------------------------------------------------
os.environ['NODE_NAME'] = node_name
os.environ['CENTRAL_SERVER_IP'] = central_server_ip
os.environ['CENTRAL_SERVER_PORT'] = str(central_server_port)
os.environ['CENTRAL_RABBITMQ_VHOST'] = central_rabbitmq_vhost
os.environ['SANDBOX_PATH'] = sandbox_path
os.environ['DATA_PATH'] = data_path
os.environ['FLOWER_SSL_CACERT'] = str(ssl_cafile_path)

