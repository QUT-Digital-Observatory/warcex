from warcex.plugmanager import WACZPlugin
#from warcex.data import RequestData, LazyResponseData
from pathlib import Path
import json
from dataclasses import asdict
from warcex.data import RequestData, ResponseData
from typing import Any, TypedDict
from bs4 import BeautifulSoup

class FacebookStoryComment(TypedDict):
    id: str
    author: str
    author_id: str
    text: str | None
    sticker: str | None
    reply_to: str | None
    created_time: int
class FacebookGroupStory(TypedDict):
    author_name: str
    author_id: str
    text: str | None
    video: str | None
    comments: list[FacebookStoryComment]
class FacebookGroup(TypedDict):
    name: str
    partial_url: str
    description: str | None
    location: str | None
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
        return ["https://www.facebook.com/api/graphql/", "https://www.facebook.com/ajax/bulk-route-definitions/", "https://www.facebook.com/groups/*"]

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
        elif "/groups/" in request_data.url:
            print('GROUP PAGE:', request_data.url)
            self._extract_group_html(response_data)
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
                node_type = data_obj['node']['__typename']
                print('Node type:', data_obj['node']['__typename'])
                if node_type == 'Story':
                    self._extract_storynode(data_obj['node'])
                elif node_type == 'Feedback':
                    print("TRIGGERING FEEDBACK EXTRACTION")
                    self._extract_feedback(data_obj['node'])
            elif 'story_card' in data_obj:
                print("TRIGGERING STORY CARD EXTRACTION")
                self._extract_story_card(data_obj)

        json_data = self._decode_json_bytes(response_data.content)
        if json_data is None:
            print("Content is not JSON.")
            with open(self.output_dir / "bad_request_json_data.dat", "wb") as fw:
                fw.write(response_data.content)
            return

        self.data_pairs.append({"request": asdict(request_data), "response_count": len(json_data), "response": json_data})

    def _extract_feedback(self, node: Any):
        if 'replies_connection' not in node:
            return
        print('EXTRACTING FEEDBACK REPLIES')
        group_id: str = node["replies_connection"]["edges"][0]["node"]["group_comment_info"]["group"]["id"]
        replies = node['replies_connection']['edges']
        for reply in replies:
            reply_node = reply['node']
            url_parts = reply_node["comment_action_links"][0]["comment"]["url"].split("/")
            post_index = url_parts.index("posts") if "posts" in url_parts else -1
            post_id = url_parts[post_index + 1] if post_index != -1 else None
            if not post_id or group_id not in self.groups:
                continue
            if post_id not in self.groups[group_id]['stories']:
                print('WARN: We have a reply to a post that we do not have:', post_id)
                continue
            existing_comments = self.groups[group_id]['stories'][post_id]['comments']
            comment_id = reply_node['id']
            if comment_id in [c['id'] for c in existing_comments]:
                print("WE HAVE THIS COMMENT ALREADY")
                continue
            comment: FacebookStoryComment = {
                "id": comment_id,  # Using legacy_fbid as you suggested
                "author": reply_node["author"]["name"],
                "author_id": reply_node["author"]["id"],
                "text": node["body"]["text"] if "body" in node else None,
                "sticker": None,  # No sticker in this example
                "reply_to": reply_node["comment_parent"]["id"] if "comment_parent" in reply_node else None,
                "created_time": reply_node["created_time"]
            }
            existing_comments.append(comment)

    def _extract_group_html(self, response_data: ResponseData) -> None:
        """
        Extracts group details from the html
        """
        content_str = response_data.content.decode('utf-8')
        soup = BeautifulSoup(content_str, 'html.parser')
        group_title = soup.title.string # type: ignore
        assert group_title is not None
        json_data = None
        for script in soup.find_all('script', type='application/json'):
            try:
                # load the JSON data from the script tag
                json_data = json.loads(script.string) # type: ignore
            except json.JSONDecodeError:
                print(f"Error decoding JSON from script tag: {script}")
                continue
            except TypeError: #script.string is none
                print("script tag has no string")
                continue

            if '"CometGroupDiscussionTabAboutCardRenderer"' in script.string:
                comment_discussion_tab_cards = self._find_objects_by_typename(json_data, "CometGroupDiscussionTabAboutCardRenderer")
                if comment_discussion_tab_cards:
                    card = comment_discussion_tab_cards[0]
                    group_id = card['group']['id']
                    group_location = card['group']['group_locations'][0]['name'] if 'group_locations' in card['group'] and card['group']['group_locations'] else None
                    group_description = card['group']['description_with_entities']['text'] if 'description_with_entities' in card['group'] else None
                    if group_id not in self.groups:
                        group: FacebookGroup = {
                            "name": group_title,
                            "location": group_location,
                            "description": group_description,
                            "partial_url": "/groups/"+card['group']['group_address'],
                            "stories": {}
                        }
                        self.groups[group_id] = group
                    else:
                        # Update these fields anyway since we don't get them from the API
                        self.groups[group_id]['location'] = group_location
                        self.groups[group_id]['description'] = group_description
            elif '"CometStorySections"' in script.string:
                print("Found Story nodes from HTML embedded JSON")
                stories = self._find_objects_by_typename(json_data, "Story")
                for story in stories:
                    if '_post_id' in story:
                        self._extract_storynode(story)
                    
        if json_data is None:
            print("No JSON data found in the HTML")
            return
        
    def _extract_story_card(self, data_obj: dict[str, Any]) -> None:
        feedback_data = data_obj['feedback']
        story_card_data = data_obj['story_card']
        self._write_debug_json(feedback_data, 'debug/feedback.json', True)
        if 'ufi_renderer' in feedback_data:
            group_id = story_card_data['target_group']['id']
            story_id = story_card_data['post_id']
            comments = feedback_data['ufi_renderer']['feedback']['comment_list_renderer']['feedback']['comment_rendering_instance_for_feed_location']['comments']['edges']
            if group_id not in self.groups:
                print('Group not found:', group_id)
                return
            if story_id not in self.groups[group_id]['stories']:
                print('Story not found:', story_id)
                print(self.groups[group_id]['stories'].keys())
                self._write_debug_json(feedback_data, 'debug/feedback_notfound.json')
                story: FacebookGroupStory = {
                    "author_name": feedback_data['ufi_renderer']['feedback']['comment_list_renderer']['feedback']['comment_rendering_instance_for_feed_location']['comments']['edges'][0]['node']['parent_feedback']['owning_profile']['name'],
                    "author_id": story_card_data['target_group']['id'],
                    "text": None,
                    "video": None,
                    "comments": []
                }
                self.groups[group_id]['stories'][story_id] = story
            else:
                print('Adding comments to existing story')
            existing_comments = self.groups[group_id]['stories'][story_id]['comments']
            for comment in comments:
                cnode = comment['node']
                comment_id = cnode['id']
                # Check if this comment is already in the list
                if comment_id in [c['id'] for c in existing_comments]:
                    print("WE HAVE THIS COMMENT ALREADY")
                    continue
                print("ADDING COMMENT")
                sticker = None
                if 'attachments' in cnode and len(cnode['attachments']) > 0:
                    media = cnode['attachments'][0]['style_type_renderer']['attachment']['media']
                    if media['__typename'] == 'Sticker':
                        sticker = media['label']
                    # We should probably support photos and videos here too
                try:
                    comment_data: FacebookStoryComment = {
                        'id': comment_id,
                        'author': cnode['author']['name'],
                        'author_id': cnode['author']['id'],
                        'text': cnode['body']['text'] if cnode['body'] is not None else None,
                        'sticker': sticker,
                        'reply_to': cnode['comment_parent'],
                        'created_time': cnode['created_time']
                    }
                except TypeError:
                    print('Error extracting comment data', cnode)
                    self._write_debug_json(cnode, 'debug/comment.json')
                    exit()
                existing_comments.append(comment_data)

            #self._write_debug_json(comments, 'debug/comments.json')

    def _extract_storynode(self, node_data: dict[str, Any]) -> None:
        try:
            story_id = node_data['post_id']
        except KeyError:
            self._write_debug_json(node_data, 'debug/storynopost.json')
            exit()
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
                'reply_to': None,
                'sticker': None,
                'created_time': comment['comment']['created_time']
            }
            comments_data.append(comment_data)

        print('Found story:', story_text)
        story: FacebookGroupStory = {
            'author_name': author_name,
            'author_id': author_id,
            'text': story_text,
            'video': video,
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

    def _write_debug_json(self, data: Any, filename: str = 'debug/debug.json', append: bool = False) -> None:
        mode = 'a' if append else 'w'
        with open(filename, mode) as f:
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
            print('Found Facebook group (no description):', group_title)
            self.groups[group_id] = {
                "name": group_title, 
                "partial_url": url_partial, 
                "stories": {},
                "location": None,
                "description": None}
    
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
        
    def _find_objects_by_typename(self, data: dict, target_typename: str):
        """
        Walks through a nested dictionary and finds all objects
        where the "__typename" property matches the target_typename.
        
        Args:
            data: A dictionary, list, or primitive value to search through
            target_typename: The typename string to match against
            
        Returns:
            A list of all objects (dictionaries) that have a matching "__typename"
        """
        results = []
        
        # Base case: data is not a dict or list
        if not isinstance(data, (dict, list)):
            return results
        
        # Case: data is a dictionary
        if isinstance(data, dict):
            # Check if this dictionary has the typename we're looking for
            if data.get("__typename") == target_typename:
                results.append(data)
            
            # Recursively search all values in this dictionary
            for value in data.values():
                results.extend(self._find_objects_by_typename(value, target_typename))
        
        # Case: data is a list
        elif isinstance(data, list):
            # Recursively search all items in this list
            for item in data:
                results.extend(self._find_objects_by_typename(item, target_typename))
        
        return results
    