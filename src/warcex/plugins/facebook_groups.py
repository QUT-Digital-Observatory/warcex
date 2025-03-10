from warcex.plugmanager import WACZPlugin
#from warcex.data import RequestData, LazyResponseData
from pathlib import Path
import json
from dataclasses import asdict
from warcex.data import RequestData, ResponseData
from typing import Any, TypedDict

class FacebookStoryComment(TypedDict):
    id: str
    author: str
    author_id: str
    text: str
    reply_to: str | None
class FacebookGroupStory(TypedDict):
    author_name: str
    author_id: str
    text: str | None
    video: str | None
    story_id: str
    comments: list[FacebookStoryComment]
class FacebookGroup(TypedDict):
    name: str
    partial_url: str
    stories: dict[str, FacebookGroupStory]

class FacebookGroupsPlugin(WACZPlugin):
    """
    Facebook Groups plugin that extracts posts and comments from a Facebook Groups page. This plugin processes GraphQL API responses and extracts the data from them.
    """

    def __init__(self, output_dir: Path):
        super().__init__(output_dir)
        self.data_pairs = [] 
        print('initialised')
        self.groups: dict[str, FacebookGroup] = {}

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
        return ["https://www.facebook.com/api/graphql/", "https://www.facebook.com/ajax/bulk-route-definitions/"]

    def extract(self, request_data: RequestData, response_data: ResponseData) -> None:
        """
        Process Facebook Groups content.

        Args:
            request_data: A dictionary containing details about the request including post_data
            response_data: The response data as a dictionary (parsed JSON) or raw bytes
        """

        # We use this to get the name and ID of groups
        if request_data.url == "https://www.facebook.com/ajax/bulk-route-definitions/":
            self._extract_route_definition(response_data)
            return
        
        # Process data
        json_data_array = self._decode_json_bytes(response_data.content)
        if json_data_array is None:
            print("Content is not JSON.")
            return
        for json_data in json_data_array:
            if not 'data' in json_data:
                print('No data field in json_data')
                return
            data_obj = json_data['data']
            if 'node' in data_obj:
                self._extract_node(data_obj['node'])

        json_data = self._decode_json_bytes(response_data.content)
        if json_data is None:
            print("Content is not JSON.")
            with open(self.output_dir / "bad_request_json_data.dat", "wb") as fw:
                fw.write(response_data.content)
            return

        self.data_pairs.append({"request": asdict(request_data), "response_count": len(json_data), "response": json_data})

    def _extract_node(self, node_data: dict[str, Any]) -> None:
        data_type = node_data['__typename']
        if data_type == 'Story':
            story_id = node_data['id']
            try:
                group_id = node_data['feedback']['associated_group']['id']
            except KeyError:
                print('associated_group', node_data['feedback']['associated_group'])
                exit()
            if story_id in self.groups[group_id]['stories']:
                return # We only load this story once
            # Create a new story entry        
            has_text: bool = node_data['comet_sections']['content']['story']['comet_sections']['message'] is not None
            if has_text:
                story_text = node_data['comet_sections']['content']['story']['comet_sections']['message']['story']['message']['text']
            else:
                story_text = None
            video = None
            if 'attachments' in node_data['comet_sections']['content']['story']:
                for attachment in node_data['comet_sections']['content']['story']['attachments']:
                    if 'target' in attachment and attachment['target']['__typename'] == 'Video':
                        video = attachment['target']['id']
            author_id = node_data['comet_sections']['content']['story']['actors'][0]['id']
            author_name = node_data['comet_sections']['content']['story']['actors'][0]['name']
            if 'story' not in node_data['comet_sections']['feedback']:
                print('No story in feedback', node_data['feedback'])
                self._write_debug_json(node_data)
                exit()
                return
            comments = node_data['comet_sections']['feedback']['story']['story_ufi_container']['story']['feedback_context']['interesting_top_level_comments']
            comments_data: list[FacebookStoryComment] = []
            for comment in comments:
                comment_data: FacebookStoryComment = {
                    'id': comment['comment']['id'],
                    'author': comment['comment']['author']['name'],
                    'author_id': comment['comment']['author']['id'],
                    'text': comment['comment']['body']['text'],
                    'reply_to': None
                }
                comments_data.append(comment_data)

            print('Found story:', story_text)
            story: FacebookGroupStory = {
                'author_name': author_name,
                'author_id': author_id,
                'text': story_text,
                'video': video,
                'story_id': story_id,
                'comments': comments_data
            }
            self.groups[group_id]['stories'][story_id] = story

    def finalise(self):
        """
        Finalize processing and generate output.
        Called after all request-response pairs have been processed.
        Use this for any operations that need to be performed after
        all data has been collected.
        """
        with open(self.output_dir / "data_pairs.json", "w") as fw:
            json.dump(self.data_pairs, fw, indent=2)

        with open(self.output_dir / "groups.json", "w") as fw:
            json.dump(self.groups, fw, indent=2)

    def _write_debug_json(self, data: Any):
        with open('debug/debug.json', 'w') as f:
            json.dump(data, f, indent=2)

    def _extract_route_definition(self, response_data: ResponseData) -> None:
        # Strip off the weird "for (;;);" garbage at the beginning of the response
        content_str = response_data.content.decode('utf-8')
        start_index = content_str.find('{')
        content_str = content_str[start_index:]
        json_data = json.loads(content_str)
        def _extract_group_info(json_data):
            payloads = json_data['payload']['payloads']
            try:
                for key, value in payloads.items():
                    if key.startswith('/groups/') and key.count('/') == 2: # Ignore all the sub group stuff
                        group_title = value['result']['exports']['meta']['title']
                        group_id = value['result']['exports']['rootView']['props']['groupID']
                        url_partial = key
                        return group_title, group_id, url_partial
                return None
            except (KeyError, TypeError):
                print ('Error extracting group info from', payloads)
                return None
        vals = _extract_group_info(json_data)
        if not vals:
            return
        group_title, group_id, url_partial = vals
        if group_id not in self.groups:
            print('Found Facebook group:', group_title)
            self.groups[group_id] = {"name": group_title, "partial_url": url_partial, "stories": {}}
    
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
        