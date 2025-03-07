from dataclasses import dataclass
from typing import Optional, Tuple, Iterator
import os
import zipfile
import tempfile
import shutil
from warcio.archiveiterator import ArchiveIterator
from warcex.plugmanager import PluginManager, WACZPlugin
from colorama import Fore, Style
from typer import echo
from pathlib import Path
from warcex.data import RequestData, ResponseData
from urllib.parse import urlparse, parse_qs

class WACZProcessor:
    """
    A class for processing Web Archive Collection Zipped (WACZ) files.
    Provides structured access to WARC records and processes request-response pairs.
    Designed to be used with a context manager.
    """

    def __init__(
        self,
        wacz_path: Path,
        output_folder: Path,
        manual_plugins: Optional[list[Path]] = None,
        only: Optional[str] = None,
    ):
        """
        Initialize the WACZProcessor with a path to a WACZ file.

        Args:
            wacz_path: Path to the WACZ file to process
            output_folder: Path where extracted data will be saved
            manual_plugins: Optional list of paths to manually loaded plugin files
            only: Optional filter to process only specific plugin(s)
        """
        self.output_dir = output_folder
        self.wacz_path = wacz_path
        self._temp_dir: Optional[str] = None
        self._zip_ref: Optional[zipfile.ZipFile] = None
        self._file_list: list[str] = []
        self._extracted_files: set[str] = set()
        self.plugin_manager = PluginManager(output_folder)
        self.only = only

        # Validate that the file exists and is a zip file
        if not os.path.exists(wacz_path):
            raise FileNotFoundError(f"WACZ file not found: {wacz_path}")

        try:
            with zipfile.ZipFile(wacz_path, "r") as zip_ref:
                self._file_list = zip_ref.namelist()
        except zipfile.BadZipFile:
            raise ValueError(f"File is not a valid ZIP/WACZ file: {wacz_path}")

        # Load plugins
        if manual_plugins:
            plugin_names = []
            for plugin_file in manual_plugins:
                try:
                    plugin_info = self.plugin_manager.sideload_plugin(plugin_file)
                except Exception as e:
                    echo(
                        f"{Fore.RED}Error loading plugin {plugin_file}: {e}{Style.RESET_ALL}"
                    )
                    raise e
                plugin_names.append(plugin_info.name)
            echo(
                f"{Fore.CYAN}Loaded plugins: {', '.join(plugin_names)}{Style.RESET_ALL}."
            )

    def _extract_file(self, file_path: str) -> str:
        """
        Extract a file from the WACZ archive to the temporary directory.

        Args:
            file_path: Path of the file within the WACZ archive

        Returns:
            Path to the extracted file
        """
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
        with self._zip_ref.open(file_path) as source, open(
            extracted_path, "wb"
        ) as target:
            shutil.copyfileobj(source, target)

        self._extracted_files.add(file_path)
        return extracted_path

    def get_warc_paths(self) -> list[str]:
        """
        Get the paths of all WARC files in the archive.

        Returns:
            List of WARC file paths within the WACZ
        """
        return [
            p for p in self._file_list if p.endswith(".warc.gz") or p.endswith(".warc")
        ]

    def extract_warc_file(self, warc_path: str) -> str:
        """
        Extract a specific WARC file from the archive.

        Args:
            warc_path: Path of the WARC file within the WACZ

        Returns:
            Path to the extracted WARC file
        """
        if not warc_path.endswith(".warc.gz") and not warc_path.endswith(".warc"):
            raise ValueError(f"Not a WARC file: {warc_path}")

        return self._extract_file(warc_path)

    def iter_request_response_pairs(
        self,
    ) -> Iterator[Tuple[RequestData, ResponseData, WACZPlugin]]:
        """
        Iterate through request-response pairs in all WARC files.
        Only processes request-response pairs that match a plugin endpoint.
        Also returns the matching plugin.

        Returns:
            Iterator of (request_data, response_data, plugin) tuples
        """
        # Keep track of statistics
        stats = {
            "total_requests": 0,
            "total_responses": 0,
            "matched_pairs": 0,
            "plugin_matched": 0
        }
        
        # Process all WARC files
        for warc_path in self.get_warc_paths():
            echo(f"{Fore.YELLOW}Processing WARC file: {warc_path}{Style.RESET_ALL}")
            extracted_warc = self.extract_warc_file(warc_path)

            # First pass: collect URL information from requests to check for plugin matches
            # Use request_id as key to handle multiple requests to the same URL
            request_info_map = {}
            with open(extracted_warc, "rb") as warc_file:
                for record in ArchiveIterator(warc_file):
                    if record.rec_type == "request":
                        stats["total_requests"] += 1
                        request_url = record.rec_headers.get_header("WARC-Target-URI")
                        concurrent_to = record.rec_headers.get_header("WARC-Concurrent-To")
                        request_id = record.rec_headers.get_header("WARC-Record-ID")
                        
                        if request_url and concurrent_to and request_id:
                            # Check if any plugin matches this URL
                            plugin = self.plugin_manager.get_plugin_for_url(request_url, only=self.only)
                            if plugin:
                                # Store request info keyed by request_id to handle multiple requests to same URL
                                request_info_map[request_id] = {
                                    "url": request_url,
                                    "concurrent_to": concurrent_to,
                                    "plugin": plugin,
                                    "method": record.http_headers.get_header("Method", "GET"),
                                    "headers": {h[0]: h[1] for h in record.http_headers.headers 
                                               if h[0] not in ("Content-Length", "Method")},
                                    "timestamp": record.rec_headers.get_header("WARC-Date", "")
                                }
            
            if not request_info_map:
                # Skip second pass if no requests matched a plugin
                continue
                
            # Second pass: collect responses that match our filtered requests
            response_map = {}
            all_concurrent_ids = [info["concurrent_to"] for info in request_info_map.values()]
            with open(extracted_warc, "rb") as warc_file:
                for record in ArchiveIterator(warc_file):
                    if record.rec_type == "response":
                        stats["total_responses"] += 1
                        record_id = record.rec_headers.get_header("WARC-Record-ID")

                        # Only process responses that are needed by matched requests
                        if record_id and record_id in all_concurrent_ids:
                            # Get response metadata
                            response_type = record.http_headers.get_header("Content-Type", "")
                            
                            try:
                                content_length = int(record.http_headers.get_header("Content-Length", "0"))
                            except ValueError:
                                content_length = None
                            
                            status_code = record.http_headers.get_statuscode()
                            
                            # Get the full content
                            content_bytes = record.content_stream().read()
                            
                            # Store response data
                            response_map[record_id] = ResponseData(
                                content=content_bytes,
                                content_type=response_type,
                                content_length=content_length,
                                status_code=status_code
                            )
            
            # Now yield matched request-response-plugin tuples
            for req_id, request_info in request_info_map.items():
                url = request_info["url"]
                concurrent_to = request_info["concurrent_to"]

                if concurrent_to in response_map:
                    # Get query parameters from URL
                    parsed_url = urlparse(url)
                    query_params = parse_qs(parsed_url.query)
                    query_data = {k: v[0] if len(v) == 1 else v for k, v in query_params.items()}
                    
                    # Get the stored response data
                    response_data = response_map[concurrent_to]
                    
                    # Create request data
                    request_data = RequestData(
                        url=url,
                        method=request_info["method"],
                        headers=request_info["headers"],
                        query_data=query_data,
                        response_type=response_data.content_type,
                        content_length=response_data.content_length,
                        timestamp=request_info["timestamp"],
                        status_code=response_data.status_code
                    )
                    
                    stats["matched_pairs"] += 1
                    stats["plugin_matched"] += 1
                    
                    yield (request_data, response_data, request_info["plugin"])
        
        # Print final statistics
        echo(f"{Fore.GREEN}Processed {stats['total_requests']} requests and {stats['total_responses']} responses{Style.RESET_ALL}")
        echo(f"{Fore.GREEN}Found {stats['matched_pairs']} matched request-response pairs{Style.RESET_ALL}")
        echo(f"{Fore.GREEN}Found {stats['plugin_matched']} pairs with matching plugins{Style.RESET_ALL}")

    @dataclass
    class ExtractionResult:
        """Results of the extraction process."""
        total_processed: int
        plugin_counts: dict[str, int]

    def extract(self) -> "WACZProcessor.ExtractionResult":
        """
        Process all request-response pairs in the archive and pass them to matching plugins.
        Only processes pairs that have a matching plugin.
        Calls finalise() on all used plugins at the end.

        Returns:
            ExtractionResult with statistics about processed items
        """
        plugin_counts: dict[str, int] = {}
        total_processed = 0

        echo(f"{Fore.CYAN}Extracting content from: {self.wacz_path}{Style.RESET_ALL}")

        # Process only pairs that have a matching plugin
        for request_data, response_data, plugin in self.iter_request_response_pairs():
            # Get plugin name for stats
            plugin_name = plugin.get_info().name
            
            try:
                # Call the plugin's extract method directly
                plugin.extract(request_data, response_data)
                
                # Update counters
                plugin_counts[plugin_name] = plugin_counts.get(plugin_name, 0) + 1
                total_processed += 1
                
            except Exception as e:
                # Log the error but continue with other pairs
                echo(f"{Fore.RED}Error processing with {plugin_name}: {e}{Style.RESET_ALL}")

        # Call finalise on all plugins that were used
        self.plugin_manager.finalise_all_plugins()

        # Create and return result object
        result = WACZProcessor.ExtractionResult(
            total_processed=total_processed, plugin_counts=plugin_counts
        )

        # Display results
        echo(
            f"{Fore.GREEN}Extracted {total_processed} items from archive{Style.RESET_ALL}"
        )
        for plugin_name, count in plugin_counts.items():
            echo(f"  - {plugin_name}: {count} items")

        return result

    def __enter__(self) -> "WACZProcessor":
        """Support for context manager protocol."""
        self._temp_dir = tempfile.mkdtemp(prefix="wacz_")
        self._zip_ref = zipfile.ZipFile(self.wacz_path, "r")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Clean up resources when exiting context."""
        if self._zip_ref is not None:
            self._zip_ref.close()
            self._zip_ref = None

        if self._temp_dir is not None and os.path.exists(self._temp_dir):
            shutil.rmtree(self._temp_dir)
            self._temp_dir = None

        self._extracted_files = set()
