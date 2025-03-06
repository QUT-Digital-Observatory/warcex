from typing import Optional, Any, TypedDict, Protocol, BinaryIO
from io import BytesIO
import json

# Use functional form of TypedDict for headers with special characters
RequestHeaders = TypedDict('RequestHeaders', {
    'Host': str,
    'Origin': str,
    'Referer': str,
    'Cookie': str,
    'Authorization': str,
    'User-Agent': str,
    'Accept-Language': str,
    'Content-Type': str
}, total=False)


class RequestData(TypedDict):
    """Type definition for request data extracted from WARC records."""
    url: str
    method: str
    headers: RequestHeaders
    post_data: dict[str, Any]
    response_type: str
    content_length: Optional[int]


class ResponseData(Protocol):
    """Protocol defining methods for accessing response data."""
    def get_content(self) -> bytes:
        """Get the full content as bytes."""
        ...
        
    def get_stream(self) -> BinaryIO:
        """Get a file-like object for streaming the content."""
        ...
        
    def get_json(self) -> dict[str, Any]:
        """Parse and return the content as JSON, if possible."""
        ...


class LazyResponseData:
    """Lazily loaded response data that provides different access methods."""
    
    def __init__(self, content_stream, content_type: str, content_length: Optional[int] = None):
        self._content_stream = content_stream
        self._content_type = content_type
        self._content_length = content_length
        self._content: Optional[bytes] = None
        self._json: Optional[dict[str, Any]] = None
        
    def get_content(self) -> bytes:
        """Get the full content as bytes, loading it if necessary."""
        if self._content is None:
            self._content = self._content_stream.read()
            # Reset the stream for future reads
            self._content_stream = BytesIO(self._content)
        return self._content
        
    def get_stream(self) -> BinaryIO:
        """Get a file-like object for streaming the content."""
        return self._content_stream
        
    def get_json(self) -> dict[str, Any] | None:
        """Parse and return the content as JSON, if possible."""
        if self._json is None:
            if 'json' in self._content_type.lower():
                try:
                    content = self.get_content().decode('utf-8')
                    self._json = json.loads(content)
                except Exception as e:
                    raise ValueError(f"Failed to parse JSON: {e}")
            else:
                raise ValueError(f"Content is not JSON. Content-Type: {self._content_type}")
        return self._json
        
    @property
    def content_type(self) -> str:
        """Get the content type."""
        return self._content_type
        
    @property
    def content_length(self) -> Optional[int]:
        """Get the content length if known."""
        return self._content_length
