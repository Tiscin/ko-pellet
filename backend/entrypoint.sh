#!/bin/bash
set -e

# Custom CA certificate support
# Drop .crt files into ./certs/ (bind mounted to /certs) to trust them

CA_DIR="/certs"
CUSTOM_BUNDLE="/data/ca-bundle.crt"
SYSTEM_BUNDLE="/etc/ssl/certs/ca-certificates.crt"

if [ -d "$CA_DIR" ] && [ "$(ls -A $CA_DIR/*.crt 2>/dev/null)" ]; then
    echo "Found custom CA certificates, building combined bundle..."

    # Start with system CAs
    cat "$SYSTEM_BUNDLE" > "$CUSTOM_BUNDLE"

    # Append custom CAs
    for cert in "$CA_DIR"/*.crt; do
        echo "" >> "$CUSTOM_BUNDLE"
        echo "# Custom CA: $(basename $cert)" >> "$CUSTOM_BUNDLE"
        cat "$cert" >> "$CUSTOM_BUNDLE"
        echo "  Added: $(basename $cert)"
    done

    # Set environment for Python requests and other tools
    export SSL_CERT_FILE="$CUSTOM_BUNDLE"
    export REQUESTS_CA_BUNDLE="$CUSTOM_BUNDLE"

    echo "Custom CA bundle ready"
fi

exec "$@"
