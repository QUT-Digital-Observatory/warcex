from warcex.plugmanager import WACZPlugin
#from warcex.data import RequestData, LazyResponseData
from pathlib import Path
import json
from dataclasses import asdict
from warcex.data import RequestData, ResponseData
class FacebookGroupsPlugin(WACZPlugin):
    """
    Facebook Groups plugin that extracts posts and comments from a Facebook Groups page. This plugin processes GraphQL API responses and extracts the data from them.
    """

    def __init__(self, output_dir: Path):
        super().__init__(output_dir)
        self.data_pairs = [] 
        print('initialised')

    def get_info(self) -> WACZPlugin.PluginInfo:
        """
        Get information about this plugin.
        """
        return WACZPlugin.PluginInfo(
            name="fb-groups",
            version=1,
            description="Facebook Groups Plugin fetches posts and comments.",
            instructions="Visit the Facebook Groups page and scroll down to load more content. Click on the comments to open them up, and keep doing this if comments remain collapsed. Then move on to the next story and repeat the process. Once you have loaded all the content you want to extract, save the Web Archive file.",
            output_data=[
                "endpoints.json",  # All REST endpoints found
                "response_formats.json",  # Data formats for each endpoint
                "api_map.json",  # Map of the API structure
            ],
        )
    
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
        return ["https://www.facebook.com/api/graphql/"]

    def extract(self, request_data: RequestData, response_data: ResponseData) -> None:
        """
        Process Facebook Groups content.

        Args:
            request_data: A dictionary containing details about the request including post_data
            response_data: The response data as a dictionary (parsed JSON) or raw bytes
        """

        json_data = self._decode_json_bytes(response_data.content)
        if json_data is None:
            print("Content is not JSON.")
            with open(self.output_dir / "bad_request_json_data.dat", "wb") as fw:
                fw.write(response_data.content)
            return
        self.data_pairs.append({"request": asdict(request_data), "response_count": len(json_data), "response": json_data})

    def finalise(self):
        """
        Finalize processing and generate output.
        Called after all request-response pairs have been processed.
        Use this for any operations that need to be performed after
        all data has been collected.
        """
        with open(self.output_dir / "data_pairs.json", "w") as fw:
            json.dump(self.data_pairs, fw, indent=2)

    def _decode_json_bytes(self, data_bytes: bytes) -> list[dict] | None:
        """
        Decodes bytes that are expected to be JSON or JSONL into a list of dictionaries.

        Args:
            data_bytes: The bytes data to decode.

        Returns:
            A list of dictionaries if the bytes contain valid JSON or JSONL, or None if no valid JSON is found.
        """
        if not data_bytes:
            return None

        try:
            data_str = data_bytes.decode('utf-8')
            try:
                # Attempt to decode as single JSON object
                return [json.loads(data_str)]
            except json.JSONDecodeError:
                # Attempt to decode as JSONL
                lines = data_str.splitlines()
                decoded_list = []
                for line in lines:
                    try:
                        decoded_list.append(json.loads(line))
                    except json.JSONDecodeError:
                        # If any line fails, return None.
                        return None
                return decoded_list

        except UnicodeDecodeError:
            return None  # Handle cases where bytes are not valid UTF-8
        except json.JSONDecodeError:
            return None # Handle cases where it is not valid json or jsonl.
        except Exception:
            return None # handle other unexpected errors.
        