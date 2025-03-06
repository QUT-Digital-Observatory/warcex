import json
import zipfile
import tempfile
import os
import importlib
import pkgutil
import inspect
from typing import Optional, Iterator, Any, Tuple, Type, List
import shutil
from warcio.archiveiterator import ArchiveIterator
from warcex.plugins import WACZPlugin

class WACZProcessor:
    """
    A class for processing Web Archive Collection Zipped (WACZ) files.
    Provides structured access to pages data, metadata, and WARC records.
    Supports a plugin system for custom extractors.
    """
    
    def __init__(self, wacz_path: str, lazy_load: bool = True):
        """
        Initialize the WACZProcessor with a path to a WACZ file.
        
        Args:
            wacz_path: Path to the WACZ file to process
            lazy_load: If True, files are extracted only when needed.
                      If False, the archive is extracted during initialization.
        """
        self.wacz_path = wacz_path
        self._temp_dir: Optional[str] = None
        self._zip_ref: Optional[zipfile.ZipFile] = None
        self._pages = None
        self._metadata = None
        self._extracted_files: set[str] = set()
        self._lazy_load = lazy_load
        self._is_open = False
        self._file_list: list[str] = []
        self._plugins: dict[str, WACZPlugin] = {}
        
        # Validate that the file exists and is a zip file
        if not os.path.exists(wacz_path):
            raise FileNotFoundError(f"WACZ file not found: {wacz_path}")
        
        try:
            with zipfile.ZipFile(wacz_path, 'r') as zip_ref:
                self._file_list = zip_ref.namelist()
        except zipfile.BadZipFile:
            raise ValueError(f"File is not a valid ZIP/WACZ file: {wacz_path}")
            
        # If not lazy loading, extract everything immediately
        if not lazy_load:
            self._open()
            self._extract_all()
    
    def _open(self):
        """Open the WACZ archive and create a temporary directory for extraction."""
        if self._is_open:
            return
        
        self._temp_dir = tempfile.mkdtemp(prefix="wacz_")
        self._zip_ref = zipfile.ZipFile(self.wacz_path, 'r')
        self._is_open = True
    
    def _extract_all(self):
        """Extract all files from the WACZ archive to the temporary directory."""
        if not self._is_open:
            self._open()
        
        for file_path in self._file_list:
            self._extract_file(file_path)
    
    def _extract_file(self, file_path: str) -> str:
        """
        Extract a file from the WACZ archive to the temporary directory.
        
        Args:
            file_path: Path of the file within the WACZ archive
            
        Returns:
            Path to the extracted file
        """
        if not self._is_open:
            self._open()
        
        if file_path in self._extracted_files:
            assert self._temp_dir is not None
            return os.path.join(self._temp_dir, file_path)
        
        if file_path not in self._file_list:
            raise ValueError(f"File {file_path} not found in WACZ archive")
        
        assert self._temp_dir is not None
        assert self._zip_ref is not None
        
        extracted_path = os.path.join(self._temp_dir, file_path)
        
        # Create directories if needed
        os.makedirs(os.path.dirname(extracted_path), exist_ok=True)
        
        # Extract the file
        with self._zip_ref.open(file_path) as source, open(extracted_path, 'wb') as target:
            shutil.copyfileobj(source, target)
        
        self._extracted_files.add(file_path)
        return extracted_path
    
    def _ensure_open(self):
        """Ensure the processor is open for operations."""
        if not self._is_open and self._lazy_load:
            raise RuntimeError("WACZProcessor is not open. Use the 'with' statement or call 'open()' first.")
    
    def open(self):
        """
        Open the WACZ processor for operations.
        Only needed when using lazy_load=True without a context manager.
        """
        self._open()
        return self
    
    @property
    def pages(self) -> list[dict[str, Any]]:
        """
        Get the pages data from the pages.jsonl file.
        
        Returns:
            List of page records as dictionaries
        """
        self._ensure_open()
        
        if self._pages is None:
            pages_paths = [p for p in self._file_list if p.endswith('pages.jsonl')]
            
            if not pages_paths:
                self._pages = []
            else:
                # Use the first pages.jsonl file found
                pages_path = pages_paths[0]
                extracted_path = self._extract_file(pages_path)
                
                self._pages = []
                with open(extracted_path, 'r') as f:
                    for line in f:
                        if line.strip():
                            self._pages.append(json.loads(line))
        
        return self._pages
    
    @property
    def metadata(self) -> dict[str, Any]:
        """
        Get the metadata from the datapackage.json file.
        
        Returns:
            Metadata as a dictionary
        """
        self._ensure_open()
        
        if self._metadata is None:
            if 'datapackage.json' not in self._file_list:
                self._metadata = {}
            else:
                extracted_path = self._extract_file('datapackage.json')
                
                with open(extracted_path, 'r') as f:
                    self._metadata = json.load(f)
        
        return self._metadata
    
    def get_warc_paths(self) -> list[str]:
        """
        Get the paths of all WARC files in the archive.
        
        Returns:
            List of WARC file paths within the WACZ
        """
        return [p for p in self._file_list if p.endswith('.warc.gz') or p.endswith('.warc')]
    
    def extract_warc_file(self, warc_path: str) -> str:
        """
        Extract a specific WARC file from the archive.
        
        Args:
            warc_path: Path of the WARC file within the WACZ
            
        Returns:
            Path to the extracted WARC file
        """
        self._ensure_open()
        
        if not warc_path.endswith('.warc.gz') and not warc_path.endswith('.warc'):
            raise ValueError(f"Not a WARC file: {warc_path}")
        
        return self._extract_file(warc_path)
    
    def iter_warc_records(self, warc_path: Optional[str] = None, 
                         rec_types: Optional[list[str]] = None) -> Iterator:
        """
        Iterate through WARC records in a specific WARC file or the first WARC file if none specified.
        
        Args:
            warc_path: Path of the WARC file within the WACZ, or None to use the first WARC
            rec_types: Filter for specific record types (e.g., 'response', 'request')
            
        Returns:
            Iterator over WARC records
        """
        self._ensure_open()
        
        warc_paths = self.get_warc_paths()
        
        if not warc_paths:
            raise ValueError("No WARC files found in the WACZ archive")
        
        if warc_path is None:
            warc_path = warc_paths[0]
        elif warc_path not in warc_paths:
            raise ValueError(f"WARC file not found in archive: {warc_path}")
        
        extracted_path = self.extract_warc_file(warc_path)
        
        # Convert single rec_type to list for consistent handling
        if isinstance(rec_types, str):
            rec_types = [rec_types]
        
        with open(extracted_path, 'rb') as warc_file:
            for record in ArchiveIterator(warc_file):
                # Filter by record type if specified
                if rec_types is None or record.rec_type in rec_types:
                    yield record
    
    def _extract_post_data(self, record) -> dict:
        """
        Extract POST data from a request record.
        
        Args:
            record: WARC request record
            
        Returns:
            Dictionary of POST data or empty dict if not a POST or no data
        """
        if record.http_headers.get_header('Content-Type') == 'application/x-www-form-urlencoded':
            try:
                # Read the form data
                content = record.content_stream().read().decode('utf-8')
                from urllib.parse import parse_qs
                return {k: v[0] if len(v) == 1 else v for k, v in parse_qs(content).items()}
            except Exception:
                return {}
        elif 'json' in record.http_headers.get_header('Content-Type', '').lower():
            try:
                # Parse JSON request body
                content = record.content_stream().read().decode('utf-8')
                return json.loads(content)
            except Exception:
                return {}
        else:
            # Unknown content type
            return {}
    
    def iter_request_response_pairs(self) -> Iterator[Tuple[dict, Any]]:
        """
        Iterate through request-response pairs in all WARC files.
        
        Returns:
            Iterator of (request_data, response_data) tuples
        """
        self._ensure_open()
        
        # Create a mapping of request IDs to request data
        request_map = {}
        
        # Process all WARC files
        for warc_path in self.get_warc_paths():
            extracted_warc = self.extract_warc_file(warc_path)
            
            # First pass: collect all requests
            with open(extracted_warc, 'rb') as warc_file:
                for record in ArchiveIterator(warc_file):
                    if record.rec_type == 'request':
                        request_id = record.rec_headers.get_header('WARC-Record-ID')
                        request_url = record.rec_headers.get_header('WARC-Target-URI')
                        request_method = record.http_headers.get_header('Method', 'GET')
                        
                        # Extract headers
                        headers = {}
                        for header in record.http_headers.headers:
                            if header[0] not in ('Content-Length', 'Method'):
                                headers[header[0]] = header[1]
                        
                        # Extract POST data if applicable
                        post_data = self._extract_post_data(record) if request_method == 'POST' else {}
                        
                        request_map[request_id] = {
                            'url': request_url,
                            'method': request_method,
                            'headers': headers,
                            'post_data': post_data
                        }
            
            # Second pass: match responses to requests
            with open(extracted_warc, 'rb') as warc_file:
                for record in ArchiveIterator(warc_file):
                    if record.rec_type == 'response':
                        response_for = record.rec_headers.get_header('WARC-Concurrent-To')
                        
                        if response_for in request_map:
                            request_data = request_map[response_for]
                            
                            # Add response content type to request data
                            request_data['response_type'] = record.http_headers.get_header('Content-Type', '')
                            
                            # Extract response data
                            content_bytes = record.content_stream().read()
                            
                            if 'json' in request_data['response_type'].lower():
                                try:
                                    content_str = content_bytes.decode('utf-8')
                                    response_data = json.loads(content_str)
                                except Exception:
                                    # If JSON parsing fails, provide raw content
                                    response_data = content_bytes
                            else:
                                # For non-JSON content, just provide the raw data
                                response_data = content_bytes
                            
                            yield (request_data, response_data)
    
    # def register_plugin(self, plugin: WACZPlugin) -> None:
    #     """
    #     Register a plugin with the processor.
        
    #     Args:
    #         plugin: WACZPlugin instance
    #     """
    #     info = plugin.get_info()
    #     name = info.get('name')
        
    #     if not name:
    #         raise ValueError("Plugin must have a name in get_info() result")
        
    #     self._plugins[name] = plugin
    

    
    # def load_plugins(self, plugins_package: str, output_dir: str) -> None:
    #     """
    #     Discover and load plugins from a package.
        
    #     Args:
    #         plugins_package: Package name where plugins are located
    #         output_dir: Base directory for plugin outputs
    #     """
    #     plugin_classes = self.discover_plugins(plugins_package)
        
    #     for plugin_class in plugin_classes:
    #         try:
    #             # Create a unique output directory for each plugin
    #             plugin_name = plugin_class.__name__.lower()
    #             plugin_output_dir = os.path.join(output_dir, plugin_name)
                
    #             # Initialize and register the plugin
    #             plugin = plugin_class(plugin_output_dir)
    #             self.register_plugin(plugin)
    #         except Exception as e:
    #             print(f"Failed to load plugin {plugin_class.__name__}: {e}")
    
    def get_supported_plugins_for_request(self, request_data: dict) -> list[str]:
        """
        Get plugins that support a specific request.
        
        Args:
            request_data: Request data dictionary
            
        Returns:
            List of plugin names that support this request
        """
        supported = []
        
        for name, plugin in self._plugins.items():
            if plugin.is_supported(request_data):
                supported.append(name)
                
        return supported
    
    def scan_archive(self) -> dict[str, list[dict]]:
        """
        Scan the archive for content supported by each plugin.
        
        Returns:
            Dictionary mapping plugin names to lists of supported request details
        """
        self._ensure_open()
        
        results = {name: [] for name in self._plugins}
        
        # Process all request-response pairs
        for request_data, _ in self.iter_request_response_pairs():
            for name, plugin in self._plugins.items():
                if plugin.is_supported(request_data):
                    # Store the request details (excluding large data)
                    request_info = {
                        'url': request_data['url'],
                        'method': request_data['method']
                    }
                    results[name].append(request_info)
        
        return results
    
    # def run_plugin(self, plugin_name: str) -> None:
    #     """
    #     Run a specific plugin on matched content.
        
    #     Args:
    #         plugin_name: Name of the plugin to run
    #     """
    #     self._ensure_open()
        
    #     if plugin_name not in self._plugins:
    #         raise ValueError(f"Plugin '{plugin_name}' not registered")
            
    #     plugin = self._plugins[plugin_name]
        
    #     # Collect all matching content
    #     matching_content = []
    #     for request_data, response_data in self.iter_request_response_pairs():
    #         if plugin.is_supported(request_data):
    #             matching_content.append((request_data, response_data))
        
    #     # Run the plugin's extract method with matched content
    #     plugin.extract(iter(matching_content))
    
    # def run_all_plugins(self) -> dict[str, dict]:
    #     """
    #     Run all registered plugins on their matched content.
        
    #     Returns:
    #         Dictionary of plugin names to their info
    #     """
    #     self._ensure_open()
        
    #     results = {}
    #     for name, plugin in self._plugins.items():
    #         try:
    #             self.run_plugin(name)
    #             results[name] = plugin.get_info()
    #         except Exception as e:
    #             results[name] = {"error": str(e)}
        
    #     return results
    
    def close(self):
        """
        Clean up temporary files and directories.
        """
        if self._zip_ref is not None:
            self._zip_ref.close()
            self._zip_ref = None
        
        if self._temp_dir is not None and os.path.exists(self._temp_dir):
            shutil.rmtree(self._temp_dir)
            self._temp_dir = None
        
        self._is_open = False
        self._extracted_files = set()
    
    def __enter__(self):
        """Support for context manager protocol."""
        self._open()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Clean up resources when exiting context."""
        self.close()
    
    def __del__(self):
        """Ensure cleanup when object is garbage collected."""
        self.close()
    