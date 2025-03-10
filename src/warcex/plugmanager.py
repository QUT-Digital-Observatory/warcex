from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, List
import os
import importlib
import pkgutil
import inspect
import re
from pathlib import Path
from typer import echo
from colorama import Fore, Style

from warcex.data import RequestData, ResponseData


class WACZPlugin(ABC):
    """Base abstract class for WACZ plugins."""

    def __init__(self, output_dir: Path):
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
            PluginInfo dataclass: name, version, description, output_data
        """
        pass

    @abstractmethod
    def get_endpoints(self) -> list[str]:
        """
        Return a list of URL patterns this plugin can process.
        Patterns can be:
        - Exact URLs
        - URL prefixes (ending with *)
        - Regular expressions (enclosed in / /)

        Returns:
            List of URL patterns
        """
        pass

    @abstractmethod
    def extract(self, request_data: RequestData, response_data: ResponseData) -> None:
        """
        Process content that matches this plugin's criteria.
        This may accumulate data internally for later processing in finalise().

        Args:
            request_data: A RequestData dataclass
            response_data: The response data
        """
        pass

    @abstractmethod
    def finalise(self) -> None:
        """
        Finalize processing and generate output.
        Called after all request-response pairs have been processed.
        Use this for any operations that need to be performed after
        all data has been collected.
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
        # Dictionary of compiled regular expressions to plugins
        self.pattern_to_plugin_map: Dict[re.Pattern, WACZPlugin] = (
            self._build_pattern_map()
        )
        print(self.pattern_to_plugin_map)
        # Statistics
        self.stats = {"total_matches": 0, "plugins_used": set()}

    def _build_pattern_map(self) -> Dict[re.Pattern, WACZPlugin]:
        """
        Build a mapping of URL patterns to plugin instances.
        Converts various pattern formats to regular expressions.

        Returns:
            Dictionary of compiled patterns to plugin instances
        """
        pattern_map = {}
        for plugin in self.plugins:
            for url_pattern in plugin.get_endpoints():
                # Convert the pattern to a regular expression
                if url_pattern.startswith("/") and url_pattern.endswith("/"):
                    # Already a regex pattern
                    regex_pattern = url_pattern[1:-1]
                elif url_pattern.endswith("*"):
                    # URL prefix pattern (e.g., "https://example.com/*")
                    regex_pattern = f"^{re.escape(url_pattern[:-1])}.*$"
                else:
                    # Exact match
                    regex_pattern = f"^{re.escape(url_pattern)}$"

                # Compile the regex and store with its plugin
                compiled_regex = re.compile(regex_pattern)
                pattern_map[compiled_regex] = plugin
        print('map', pattern_map)
        return pattern_map

    def get_plugin_for_url(
        self, url: str, only: Optional[str] = None
    ) -> Optional[WACZPlugin]:
        """
        Find a plugin that can handle the given URL.

        Args:
            url: The request URL to find a plugin for
            only: Optional filter to only consider a specific plugin

        Returns:
            A plugin instance or None if no plugin matches
        """
        # If 'only' is specified, find just that plugin
        if only:
            target_plugins = [p for p in self.plugins if p.get_info().name == only]
            if not target_plugins:
                return None

            # Check if any of the target plugin's patterns match
            for pattern, plugin in self.pattern_to_plugin_map.items():
                if plugin in target_plugins and pattern.search(url):

                    self.stats["total_matches"] += 1
                    self.stats["plugins_used"].add(plugin.get_info().name)
                    return plugin

            return None

        # Otherwise, check all plugins
        for pattern, plugin in self.pattern_to_plugin_map.items():
            if pattern.search(url):
                self.stats["total_matches"] += 1
                self.stats["plugins_used"].add(plugin.get_info().name)
                return plugin

        return None

    def finalise_all_plugins(self) -> None:
        """
        Call finalise on all plugins that were used.
        """
        for plugin in self.plugins:
            if plugin.get_info().name in self.stats["plugins_used"]:
                try:
                    echo(f"  Finalizing plugin: {plugin.get_info().name}...")
                    plugin.finalise()
                except Exception as e:
                    # Log the error but continue with other plugins
                    echo(
                        f"{Fore.RED}Error finalizing plugin {plugin.get_info().name}: {e}{Style.RESET_ALL}"
                    )

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
                echo(f"Error loading plugin {name}: {e}")
                continue
            except Exception as e:
                echo(f"Unexpected error instantiating {name}: {e}")
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
                    # Rebuild the pattern map to include this plugin
                    self.pattern_to_plugin_map = self._build_pattern_map()
                    break

            if plugin_instance is None:
                raise ValueError(f"No valid WACZPlugin found in {plugin_file}")

        except (ImportError, AttributeError) as e:
            echo(f"Error loading plugin {plugin_file}: {e}")
            raise
        except Exception as e:
            echo(f"Unexpected error instantiating plugin from {plugin_file}: {e}")
            raise

        return plugin_instance.get_info()
