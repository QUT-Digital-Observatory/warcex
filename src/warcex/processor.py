import json
import zipfile
import tempfile
import os
from typing import Optional, Iterator, Any
from dataclasses import dataclass
import shutil
from warcio.archiveiterator import ArchiveIterator
from warcex.plugmanager import PluginManager
from colorama import Fore, Style
from typer import echo
from pathlib import Path
from warcex.data import RequestData, LazyResponseData, RequestHeaders


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

    def _extract_post_data(self, record) -> dict[str, Any]:
        """
        Extract POST data from a request record.

        Args:
            record: WARC request record

        Returns:
            Dictionary of POST data or empty dict if not a POST or no data
        """
        if (
            record.http_headers.get_header("Content-Type")
            == "application/x-www-form-urlencoded"
        ):
            try:
                # Read the form data
                content = record.content_stream().read().decode("utf-8")
                from urllib.parse import parse_qs

                return {
                    k: v[0] if len(v) == 1 else v for k, v in parse_qs(content).items()
                }
            except Exception:
                return {}
        elif "json" in record.http_headers.get_header("Content-Type", "").lower():
            try:
                # Parse JSON request body
                content = record.content_stream().read().decode("utf-8")
                return json.loads(content)
            except Exception:
                return {}
        else:
            # Unknown content type
            return {}

    def iter_request_response_pairs(
        self,
    ) -> Iterator[tuple[RequestData, LazyResponseData]]:
        """
        Iterate through request-response pairs in all WARC files.

        Returns:
            Iterator of (request_data, response_data) tuples
        """
        # Create a mapping of request IDs to request data
        request_map: dict[str, RequestData] = {}

        # Process all WARC files
        for warc_path in self.get_warc_paths():
            extracted_warc = self.extract_warc_file(warc_path)

            # First pass: collect all requests
            with open(extracted_warc, "rb") as warc_file:
                for record in ArchiveIterator(warc_file):
                    if record.rec_type == "request":
                        request_id = record.rec_headers.get_header("WARC-Record-ID")
                        request_url = record.rec_headers.get_header("WARC-Target-URI")
                        request_method = record.http_headers.get_header("Method", "GET")

                        # Extract headers
                        headers: RequestHeaders = {}
                        for header in record.http_headers.headers:
                            if header[0] not in ("Content-Length", "Method"):
                                headers[header[0]] = header[1]

                        # Extract POST data if applicable
                        post_data = (
                            self._extract_post_data(record)
                            if request_method == "POST"
                            else {}
                        )

                        request_data: RequestData = {
                            "url": request_url,
                            "method": request_method,
                            "headers": headers,
                            "post_data": post_data,
                            "response_type": "",  # Will be filled when processing response
                            "content_length": None,
                        }
                        request_map[request_id] = request_data

            # Second pass: match responses to requests
            with open(extracted_warc, "rb") as warc_file:
                for record in ArchiveIterator(warc_file):
                    if record.rec_type == "response":
                        response_for = record.rec_headers.get_header("WARC-Concurrent-To")

                        if response_for in request_map:
                            request_data = request_map[response_for]

                            # Add response metadata to request data
                            response_type = record.http_headers.get_header(
                                "Content-Type", ""
                            )
                            request_data["response_type"] = response_type

                            try:
                                content_length = int(
                                    record.http_headers.get_header("Content-Length", "0")
                                )
                            except ValueError:
                                content_length = None

                            request_data["content_length"] = content_length

                            # Create lazy response data object
                            response_data = LazyResponseData(
                                record.content_stream(), response_type, content_length
                            )

                            yield (request_data, response_data)

    @dataclass
    class ExtractionResult:
        """Results of the extraction process."""

        total_processed: int
        plugin_counts: dict[str, int]

    def extract(self) -> "WACZProcessor.ExtractionResult":
        """
        Process all request-response pairs in the archive and pass them to the PluginManager.

        Returns:
            ExtractionResult with statistics about processed items
        """
        plugin_counts: dict[str, int] = {}
        total_processed = 0

        echo(f"{Fore.CYAN}Extracting content from: {self.wacz_path}{Style.RESET_ALL}")

        # Process each request-response pair
        for request_data, response_data in self.iter_request_response_pairs():
            # Let the plugin manager handle plugin selection and processing
            processed = self.plugin_manager.process_content(
                request_data, response_data, only=self.only
            )

            # Update counters based on processed results
            if processed:
                for plugin_name in processed:
                    plugin_counts[plugin_name] = plugin_counts.get(plugin_name, 0) + 1
                    total_processed += 1

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
