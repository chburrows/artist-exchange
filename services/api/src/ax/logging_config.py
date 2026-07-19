"""Logging setup shared by the CLI and the API.

Exists for one specific reason: **httpx logs the full request URL at INFO
level**, and every Last.fm request carries `api_key` as a query parameter.
Left at default, the first live snapshot run writes the API key into the
logs — locally that is untidy, on Railway it means a production secret
sitting in a log aggregator that has a different access policy than the
secret store does.

Raising httpx to WARNING keeps failures visible while dropping the
one-line-per-request URL dump.
"""

import logging

# Loggers that emit credentials or per-request noise at INFO.
_NOISY = {
    # Logs "HTTP Request: GET <full url with api_key=...>" per request.
    "httpx": logging.WARNING,
    "httpcore": logging.WARNING,
}


def configure_third_party_logging() -> None:
    for name, level in _NOISY.items():
        logging.getLogger(name).setLevel(level)
