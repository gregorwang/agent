"""
Poe API Client for Memory Extraction

Uses GPT-5-nano or similar cheap models via Poe API for
extracting memories from conversations.
"""

import os
import json
import asyncio
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

try:
    import aiohttp
except ImportError:
    aiohttp = None


@dataclass
class PoeConfig:
    """Poe API configuration."""
    api_key: str
    base_url: str = "https://api.poe.com/v1/chat/completions"
    model: str = "gpt-5-nano"
    timeout: int = 30


class PoeClient:
    """
    Async client for Poe API.
    
    Used for memory extraction with cheap/fast models like GPT-5-nano.
    """
    
    def __init__(self, config: Optional[PoeConfig] = None):
        """Initialize Poe client."""
        if config:
            self.config = config
        else:
            # Load from environment
            api_key = os.getenv("POE_API_KEY", "")
            model = os.getenv("POE_EXTRACTION_MODEL", "gpt-5-nano")
            self.config = PoeConfig(api_key=api_key, model=model)
        
        self._session: Optional[aiohttp.ClientSession] = None
    
    @property
    def is_configured(self) -> bool:
        """Check if API key is configured."""
        return bool(self.config.api_key)
    
    async def _get_session(self) -> "aiohttp.ClientSession":
        """Get or create aiohttp session."""
        if aiohttp is None:
            raise ImportError("aiohttp is required for Poe API. Install with: pip install aiohttp")
        
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.config.timeout)
            )
        return self._session
    
    async def close(self) -> None:
        """Close the session."""
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 1000
    ) -> Optional[str]:
        """
        Send a chat completion request.
        
        Args:
            messages: List of message dicts with "role" and "content"
            model: Model to use (defaults to config model)
            temperature: Sampling temperature
            max_tokens: Maximum response tokens
            
        Returns:
            Response content string, or None on error
        """
        if not self.is_configured:
            return None
        
        session = await self._get_session()
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}"
        }
        
        payload = {
            "model": model or self.config.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        
        try:
            async with session.post(
                self.config.base_url,
                headers=headers,
                json=payload
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    print(f"Poe API error: {response.status} - {error_text}")
                    return None
                
                data = await response.json()
                
                # Extract content from response
                if "choices" in data and len(data["choices"]) > 0:
                    return data["choices"][0].get("message", {}).get("content", "")
                
                return None
                
        except asyncio.TimeoutError:
            print("Poe API timeout")
            return None
        except Exception as e:
            print(f"Poe API error: {e}")
            return None
    
    async def test_connection(self) -> bool:
        """Test API connection."""
        if not self.is_configured:
            print("Poe API not configured (missing POE_API_KEY)")
            return False
        
        result = await self.chat([
            {"role": "user", "content": "Say 'OK' if you can hear me."}
        ], max_tokens=10)
        
        success = result is not None and "OK" in result.upper()
        if success:
            print(f"Poe API connection successful (model: {self.config.model})")
        else:
            print(f"Poe API connection failed")
        
        return success


# Global instance
_poe_client: Optional[PoeClient] = None


def get_poe_client() -> PoeClient:
    """Get or create the global PoeClient instance."""
    global _poe_client
    if _poe_client is None:
        _poe_client = PoeClient()
    return _poe_client
