from typing import Optional, Union
from dataclasses import dataclass, field

# Type alias for headers
RequestHeaders = dict[str, str]

@dataclass
class RequestData:
    """Data structure for storing request information with response metadata."""
    url: str
    method: str
    headers: RequestHeaders
    
    # Optional fields with explicit defaults
    query_data: dict[str, Union[str, list[str]]] = field(default_factory=dict)
    response_type: str = ""
    content_length: Optional[int] = None
    timestamp: str = ""
    status_code: Optional[int] = None

@dataclass
class ResponseData:
    """Data structure for storing response content and metadata."""
    content: bytes
    content_type: str = ""
    content_length: Optional[int] = None
    status_code: Optional[int] = None
