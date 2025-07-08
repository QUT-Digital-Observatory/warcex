# WARCex - Warc Extractor

This is an extensible command line tool for extracting data out of WACZ files. The tool is intended to support good research practice by utilising web archives as reproduceable research artifacts. A key use case is extracting data from walled garden websites such as social media platforms, where the data is not easily accessible through APIs, and web scraping is is problematic due to the dynamic nature of the content, and HTML obfuscation tactics. 

WARCex is an ARDC-funded work package under the [Australian Internet Observatory](https://internetobservatory.org.au/).

Developed by the [Digital Observatory](https://www.digitalobservatory.net.au/) team at the [Queensland University of Technology](https://www.qut.edu.au/) (QUT).

## Recording Web Archives

WACZ web archives can be easily recorded using the [Webrecorder ArchiveWeb.page Chrome extension](https://chromewebstore.google.com/detail/webrecorder-archivewebpag/fpeoodllldobpkbkabpblcfaogecpndd). See also [Awesome Web Archiving](https://github.com/iipc/awesome-web-archiving) for more tools and resources.

## The WARCex Tool

WARCex is intended to extract structured data from Web Archive Collections (WACZ) files. The way it works is that HTTP requests in the web archive, and their corresponding responses, are passed to a series of plugins. Each plugin can decide if it can process the request and response, and if so, extract data from them. The extracted data is then written to an output directory.

WARCex plugins can extract data from the HTTP requests and responses in the WACZ file with a variety of techniques ranging from web scraping to API reverse engineering. Since web archives are a recording of a web session, some platforms will require the researcher to perform a series of actions so that the data is shown to the user. We cannot extract what was not 'seen' by the browser in the course of making a web archive.

You can write your own plugins and pass them to WARCex:

```bash
warcx --plugin my_plugin.py extract my_wacz_file.wacz my_output_folder/
poetry run warcex extract --plugin src/warcex/plugins/facebook_groups.py ~/Downloads/facebook_my-archiving-session.wacz --output-dir ~/Downloads/facebook_my-archiving-session_ouptut/
```
You can specify mroe than one.

You can see what plugins are available by running:

```bash
warcx plugins
```

And you can get more information about a plugin including instructions on web archiving activity by running:

```bash
warcx info <plugin-name>
```

## Installation

WARCex requires Python 3.12 or later. You can install it using pip:

```bash
pip install +git://github.com/QUT-Digital-Observatory/warcex.git
```

## Usage help

```bash
warcex --help
```
## Architecture of Plugins

You can write your own plugins to extract data from WARC files. 

The pattern for a plugin by implementing the `WACZPlugin` abstract class. `is_supported` should return a bool indicating if the plugin can process the request, where the request_data from the web archive is passed in. `extract` is where the plugin processes the request and response data and writes an output to the output directory. The output file should be specified in the `output_data` field of the `PluginInfo` dataclass.

See [src/warcex/plugins](src/warcex/plugins) for some example plugins.

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
