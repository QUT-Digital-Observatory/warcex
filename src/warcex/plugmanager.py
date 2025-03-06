from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Iterator, Any
import os
import importlib
import pkgutil
import inspect


class WACZPlugin(ABC):
    """Base abstract class for WACZ plugins."""

    def __init__(self, output_dir: str):
        """
        Initialize the plugin with an output directory.

        Args:
            output_dir: Directory where extracted data will be saved
        """
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    @dataclass
    class PluginInfo:
        """Data class for plugin information."""

        name: str
        version: int
        description: str
        instructions: Optional[str]
        output_data: list[str]

    @abstractmethod
    def get_info(self) -> "WACZPlugin.PluginInfo":
        """
        Get information about the plugin.

        Returns:
            Dictionary with keys: name, version, description, output_data
        """
        pass

    @abstractmethod
    def is_supported(self, request_data: dict) -> bool:
        """
        Determine if this plugin supports the given web request.

        Args:
            request_data: Dictionary containing details about the request including:
                          - url: URL of the request
                          - method: HTTP method (GET, POST, etc.)
                          - headers: HTTP headers
                          - post_data: Parsed form data or request body
                          - response_type: Content type of the response

        Returns:
            True if this plugin can process the request
        """
        pass

    @abstractmethod
    def extract(self, content_iterator: Iterator[tuple[dict, Any]]) -> None:
        """
        Process content that matches this plugin's criteria.

        Args:
            content_iterator: Iterator of (request_data, response_data) tuples
        """
        pass


class PluginManager:
    """Class to manage WACZ plugins."""

    def __init__(self, output_dir: str):
        """
        Initialize the plugin manager with an output directory.

        Args:
            output_dir: Directory where extracted data will be saved
        """
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        self.plugins: list[WACZPlugin] = self.discover_plugins("warcex.plugins")

    def process_content(self, content_iterator: Iterator[tuple[dict, Any]]) -> None:
        """
        Process content using the registered plugins.

        Args:
            content_iterator: Iterator of (request_data, response_data) tuples
        """
        for request_data, response_data in content_iterator:
            for plugin in self.plugins:
                if plugin.is_supported(request_data):
                    plugin.extract(content_iterator)

    def discover_plugins(self, plugins_package: str) -> list[WACZPlugin]:
        """
        Discover plugins from a package.

        Args:
            plugins_package: Package name where plugins are located

        Returns:
            List of discovered plugin instances
        """
        try:
            package = importlib.import_module(plugins_package)
        except ImportError:
            return []

        plugin_instances = []

        for _, name, is_pkg in pkgutil.iter_modules(
            package.__path__, package.__name__ + "."
        ):
            if is_pkg:
                continue

            try:
                module = importlib.import_module(name)
                for item_name, item in inspect.getmembers(module, inspect.isclass):
                    if (
                        issubclass(item, WACZPlugin)
                        and item is not WACZPlugin
                        and item.__module__ == module.__name__
                    ):
                        # Create a plugin-specific output directory
                        plugin_output_dir = os.path.join(self.output_dir, item_name)
                        # Instantiate the plugin with its output directory
                        plugin_instance = item(plugin_output_dir)
                        plugin_instances.append(plugin_instance)
            except (ImportError, AttributeError) as e:
                print(f"Error loading plugin {name}: {e}")
                continue
            except Exception as e:
                print(f"Unexpected error instantiating {name}: {e}")
                continue

        return plugin_instances
