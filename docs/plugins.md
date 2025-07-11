---
title: "Plugins"
---

## Facebook Groups

```bash
warcx --plugin fb-groups extract my_input_file.wacz my_output_folder/
```

You can specify more than one WACZ files.

## Write your own plugin

You can write your own plugins and pass them to WARCex:

```bash
warcx --plugin my_plugin.py extract my_wacz_file.wacz my_output_folder/
``` 

The pattern for a plugin by implementing the `WACZPlugin` abstract class. `is_supported` should return a bool indicating if the plugin can process the request, where the request_data from the web archive is passed in. `extract` is where the plugin processes the request and response data and writes an output to the output directory. The output file should be specified in the `output_data` field of the `PluginInfo` dataclass.

See [this page](https://github.com/QUT-Digital-Observatory/warcex/tree/master/src/warcex/plugins) for some example plugins.

```python
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
```