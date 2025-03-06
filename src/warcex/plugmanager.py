from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
import os
import importlib
import pkgutil
import inspect
from pathlib import Path
from warcex.data import RequestData, LazyResponseData
from typer import echo
from colorama import Fore, Style

class WACZPlugin(ABC):
    """Base abstract class for WACZ plugins."""

    def __init__(self, output_dir: Path):
        """
        Initialize the plugin with an output directory.

        Args:
            output_dir: Directory where extracted data will be saved
        """
        self.output_dir = output_dir

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
            PluginInfo dataclass: name, version, description, output_data
        """
        pass

    @abstractmethod
    def is_supported(self, request_data: RequestData) -> bool:
        """
        Determine if this plugin supports the given web request.

        Args:
            request_data: A RequestData dictionary with the following keys
                          - url: URL of the request
                          - method: HTTP method (GET, POST, etc.)
                          - headers: RequestHeaders dictionary (HTTP headers)
                          - post_data: Parsed form data or request body
                          - response_type: Content type of the response

        Returns:
            True if this plugin can process the request
        """
        pass

    @abstractmethod
    def extract(self, request_data: RequestData, response_data: LazyResponseData) -> None:
        """
        Process content that matches this plugin's criteria.

        Args:
            request_data: A dictionary containing details about the request including post_data
            response_data: The response data as a dictionary (parsed JSON) or raw bytes
        """
        pass


class PluginManager:
    """Class to manage WACZ plugins."""

    def __init__(self, output_dir: Path):
        """
        Initialize the plugin manager with an output directory.

        Args:
            output_dir: Directory where extracted data will be saved
        """
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        self.plugins: list[WACZPlugin] = self.discover_plugins("warcex.plugins")

    def process_content(
        self, 
        request_data: RequestData, 
        response_data: LazyResponseData, 
        only: Optional[str] = None
    ) -> list[str]:
        """
        Process content through appropriate plugins.
        
        Args:
            request_data: The request data dictionary
            response_data: The lazily-loaded response data
            only: Optional filter to process only a specific plugin
            
        Returns:
            List of plugin names that successfully processed the content
        """
        successful_plugins = []
        
        # Get plugins that support this request
        plugins_to_try = []
        
        if only:
            # If 'only' is specified, find just that plugin
            for plugin in self.plugins:
                if plugin.get_info().name == only and plugin.is_supported(request_data):
                    plugins_to_try.append(plugin)
                    break
        else:
            # Otherwise, find all plugins that support this request
            plugins_to_try = [p for p in self.plugins if p.is_supported(request_data)]
        
        # Process with each plugin
        for plugin in plugins_to_try:
            try:
                plugin_name = plugin.get_info().name
                echo(f"  Processing with {plugin_name}...")
                
                # Call the plugin's extract method
                plugin.extract(request_data, response_data)
                
                # If we got here without exception, it was successful
                successful_plugins.append(plugin_name)
                
            except Exception as e:
                # Log the error but continue with other plugins
                echo(f"{Fore.RED}Error processing with {plugin.get_info().name}: {e}{Style.RESET_ALL}")
                
        return successful_plugins

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
                        plugin_output_dir = self.output_dir / item_name
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

    def sideload_plugin(self, plugin_file: Path) -> WACZPlugin.PluginInfo:
        """
        Sideload a plugin from a file.

        Args:
            plugin_file: Path to the plugin file

        Returns:
            Plugin information object
        """
        if not plugin_file.exists():
            raise FileNotFoundError(f"Plugin file not found: {plugin_file}")
            
        plugin_instance = None
        try:
            # Get the module name from the file name (without extension)
            module_name = plugin_file.stem
            
            # Use importlib.util to load the module from file path
            import importlib.util
            spec = importlib.util.spec_from_file_location(module_name, plugin_file)
            if spec is None or spec.loader is None:
                raise ImportError(f"Could not load spec for {plugin_file}")
                
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # Find plugin classes in the module
            for item_name, item in inspect.getmembers(module, inspect.isclass):
                if (
                    issubclass(item, WACZPlugin)
                    and item is not WACZPlugin
                    and item.__module__ == module.__name__
                ):
                    # Create a plugin-specific output directory
                    plugin_output_dir = self.output_dir / item_name
                    # Instantiate the plugin with its output directory
                    plugin_instance = item(plugin_output_dir)
                    self.plugins.append(plugin_instance)
                    break
                    
            if plugin_instance is None:
                raise ValueError(f"No valid WACZPlugin found in {plugin_file}")
                
        except (ImportError, AttributeError) as e:
            print(f"Error loading plugin {plugin_file}: {e}")
            raise
        except Exception as e:
            print(f"Unexpected error instantiating plugin from {plugin_file}: {e}")
            raise
            
        return plugin_instance.get_info()
