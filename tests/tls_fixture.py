"""Generate a temporary loopback certificate for HTTPS setup regression tests."""

from pathlib import Path
import ssl
import subprocess
import sys


def tls_context(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    cert, key = folder / "cert.pem", folder / "key.pem"
    config = folder / "openssl.cnf"
    config.write_text("[req]\nprompt=no\ndistinguished_name=dn\nx509_extensions=ext\n"
                      "[dn]\nCN=127.0.0.1\n[ext]\nsubjectAltName=IP:127.0.0.1\n"
                      "basicConstraints=critical,CA:TRUE\n")
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                    "-keyout", str(key), "-out", str(cert), "-config", str(config)],
                   check=True, capture_output=True)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    return context, str(cert)


if __name__ == "__main__":
    tls_context(sys.argv[1])
