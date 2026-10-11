"""Saaf gateway: PII-masking proxy for OpenAI- and Anthropic-compatible APIs."""

from saaf_gateway.app import create_app
from saaf_gateway.config import GatewayConfig

__all__ = ["GatewayConfig", "create_app"]
__version__ = "0.1.0.dev0"
