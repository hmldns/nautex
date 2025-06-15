"""Nautex API Client for low-level HTTP communication."""

import asyncio
import logging
from typing import Optional, Dict, Any
import aiohttp
import json


# Set up logging
logger = logging.getLogger(__name__)


class NautexAPIError(Exception):
    """Custom exception for Nautex API errors."""
    
    def __init__(self, message: str, status_code: Optional[int] = None, response_body: Optional[str] = None):
        """Initialize with error details.
        
        Args:
            message: Error message
            status_code: HTTP status code if applicable
            response_body: Response body content if available
        """
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class NautexAPIClient:
    """Low-level asynchronous HTTP client for Nautex.ai API."""
    
    def __init__(self, base_url: str):
        """Initialize the API client.
        
        Args:
            base_url: Base URL for the Nautex.ai API
        """
        self.base_url = base_url.rstrip('/')
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self._ensure_session()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
    
    async def _ensure_session(self):
        """Ensure aiohttp session is created."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30, connect=10)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers={'Content-Type': 'application/json'}
            )
    
    async def close(self):
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
    
    async def _request(
        self, 
        method: str, 
        endpoint_url: str, 
        headers: Optional[Dict[str, str]] = None, 
        json_payload: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Make an HTTP request with retry logic.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint_url: Full endpoint URL
            headers: Request headers
            json_payload: JSON request body
            
        Returns:
            Parsed JSON response
            
        Raises:
            NautexAPIError: For API errors
        """
        await self._ensure_session()
        
        # Merge headers
        request_headers = {}
        if headers:
            request_headers.update(headers)
        
        # Retry configuration
        max_retries = 3
        retry_delays = [1, 2, 4]  # Exponential backoff in seconds
        
        last_exception = None
        
        for attempt in range(max_retries):
            try:
                logger.debug(f"API request attempt {attempt + 1}/{max_retries}: {method} {endpoint_url}")
                
                # Prepare request kwargs
                request_kwargs = {
                    'method': method,
                    'url': endpoint_url,
                    'headers': request_headers
                }
                
                if json_payload is not None:
                    request_kwargs['json'] = json_payload
                
                async with self._session.request(**request_kwargs) as response:
                    response_text = await response.text()
                    
                    # Check for successful response
                    if 200 <= response.status < 300:
                        try:
                            return await response.json()
                        except (json.JSONDecodeError, aiohttp.ContentTypeError) as e:
                            logger.error(f"Failed to parse JSON response: {e}")
                            raise NautexAPIError(
                                f"Invalid JSON response: {str(e)}", 
                                status_code=response.status,
                                response_body=response_text
                            )
                    
                    # Handle client errors (4xx) - don't retry
                    elif 400 <= response.status < 500:
                        logger.error(f"Client error {response.status}: {response_text}")
                        raise NautexAPIError(
                            f"Client error {response.status}: {response_text}",
                            status_code=response.status,
                            response_body=response_text
                        )
                    
                    # Handle server errors (5xx) - retry these
                    elif response.status >= 500:
                        error_msg = f"Server error {response.status}: {response_text}"
                        logger.warning(f"Attempt {attempt + 1} failed: {error_msg}")
                        last_exception = NautexAPIError(
                            error_msg,
                            status_code=response.status,
                            response_body=response_text
                        )
                        
                        # Don't sleep after the last attempt
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delays[attempt])
                        continue
                    
                    else:
                        # Unexpected status code
                        error_msg = f"Unexpected response status {response.status}: {response_text}"
                        logger.error(error_msg)
                        raise NautexAPIError(
                            error_msg,
                            status_code=response.status,
                            response_body=response_text
                        )
            
            except aiohttp.ClientError as e:
                # Network-level errors - retry these
                error_msg = f"Network error: {str(e)}"
                logger.warning(f"Attempt {attempt + 1} failed: {error_msg}")
                last_exception = NautexAPIError(f"Network error after {max_retries} attempts: {str(e)}")
                
                # Don't sleep after the last attempt
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delays[attempt])
                continue
            
            except NautexAPIError:
                # Re-raise our own exceptions (4xx errors, JSON parsing errors, etc.)
                raise
            
            except Exception as e:
                # Unexpected errors - don't retry
                logger.error(f"Unexpected error: {str(e)}")
                raise NautexAPIError(f"Unexpected error: {str(e)}")
        
        # If we get here, all retries failed
        if last_exception:
            raise last_exception
        else:
            raise NautexAPIError(f"Request failed after {max_retries} attempts")
    
    async def get(self, endpoint_url: str, headers: Dict[str, str]) -> Dict[str, Any]:
        """Make a GET request.
        
        Args:
            endpoint_url: Full endpoint URL
            headers: Request headers
            
        Returns:
            Parsed JSON response
        """
        return await self._request("GET", endpoint_url, headers)
    
    async def post(
        self, 
        endpoint_url: str, 
        headers: Dict[str, str], 
        json_payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Make a POST request.
        
        Args:
            endpoint_url: Full endpoint URL
            headers: Request headers
            json_payload: JSON request body
            
        Returns:
            Parsed JSON response
        """
        return await self._request("POST", endpoint_url, headers, json_payload) 