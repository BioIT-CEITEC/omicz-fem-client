#!/bin/bash
cd config

# Clone the CA certificate from GitHub
git clone https://gitlab.bsc.es/fl/rabbitmq-ca.git
cd rabbitmq-ca

# Generate client private key
openssl genpkey -algorithm RSA -out client_key.pem

# Generate client certificate signing request (CSR)
openssl req -new -key client_key.pem -out client_csr.pem -subj "/CN=Client/C=ES"

# Generate client certificate
openssl x509 -req -in client_csr.pem -CA rootCA_cert.pem -CAkey rootCA_key.pem -out client_cert.pem -set_serial $(date +%s) -days 36500



