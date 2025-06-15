"""Nautex API module with client factory for production and test modes."""

from .client import NautexAPIClient, NautexAPIError
from .test_client import NautexTestAPIClient


def create_api_client(base_url: str = "https://api.nautex.ai", test_mode: bool = True):
    """Factory function to create the appropriate API client.
    
    Args:
        base_url: Base URL for the API (ignored in test mode)
        test_mode: If True, returns test client with dummy responses
        
    Returns:
        NautexTestAPIClient if test_mode=True, otherwise NautexAPIClient
    """
    if test_mode:
        return NautexTestAPIClient(base_url)
    else:
        return NautexAPIClient(base_url)


__all__ = [
    'NautexAPIClient',
    'NautexTestAPIClient', 
    'NautexAPIError',
    'create_api_client'
]
