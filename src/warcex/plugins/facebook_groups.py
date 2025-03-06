from warcex.plugmanager import WACZPlugin
from typing import Iterator, Any
from pathlib import Path
class FacebookGroupsPlugin(WACZPlugin):
    """
    Facebook Groups plugin that extracts posts and comments from a Facebook Groups page. This plugin processes GraphQL API responses and extracts the data from them.
    """
    
    def __init__(self, output_dir: Path):
        super().__init__(output_dir)
    
    def get_info(self) -> WACZPlugin.PluginInfo:
        """
        Get information about this plugin.
        """
        return WACZPlugin.PluginInfo(
            name = "fb-groups",
            version = 1,
            description = "Facebook Groups Plugin fetches posts and comments.",
            instructions = "Visit the Facebook Groups page and scroll down to load more content. Click on the comments to open them up, and keep doing this if comments remain collapsed. Then move on to the next story and repeat the process. Once you have loaded all the content you want to extract, save the Web Archive file.",
            output_data = [
                "endpoints.json",        # All REST endpoints found
                "response_formats.json", # Data formats for each endpoint
                "api_map.json"           # Map of the API structure
            ]
        )
    
    def is_supported(self, request_data: dict) -> bool:
        """
        Check if this request is a Facebook GraphQL request for group data.
        
        Args:
            request_data: Request data dictionary
            
        Returns:
            True if this is a Facebook Groups GraphQL request
        """
        # First check if it's a Facebook GraphQL request
        if not request_data['url'].startswith('https://www.facebook.com/api/graphql'):
            return False
        
        # Check method
        if request_data['method'] != 'POST':
            return False
            
        # Look for group-related requests in the POST data
        post_data = request_data.get('post_data', {})
        
        # Check for specific GraphQL friendly_name indicators
        friendly_name = None
        
        # If post_data is a string, it might be a form-encoded string that wasn't parsed
        if isinstance(post_data, str):
            if 'fb_api_req_friendly_name=' in post_data:
                for part in post_data.split('&'):
                    if part.startswith('fb_api_req_friendly_name='):
                        friendly_name = part.split('=')[1]
                        break
        elif isinstance(post_data, dict):
            friendly_name = post_data.get('fb_api_req_friendly_name')
        
        # Check if friendly_name indicates a group-related request
        # Let's just assume we support these:
        # But in the first instance we want GroupsCometFeedRegularStoriesPaginationQuery for the stories in a group
        if friendly_name:
            group_queries = [
                'GroupsCometFeedRegularStoriesPaginationQuery',
                'GroupsCometFeedRegularStoriesQuery',
                'GroupsCometFeedStoryQuery',
                'GroupsCometMembersPageNewMembersSectionQuery',
                'GroupsCometMembersPaginationQuery', 
                'GroupsCometEntityMenuEmbeddedQuery',
                'GroupsCometComposerDialogQuery',
                'GroupsCometCommunityVoiceQuery',
                'GroupsCometDiscussionNullstateCTAQuery'
            ]
            
            return any(query in friendly_name for query in group_queries)
        
        return False
    
    def extract(self, content_iterator: Iterator[tuple[dict, Any]]) -> None:
        """
        Process Facebook Groups content.
        
        Args:
            content_iterator: Iterator of (request_data, response_data) tuples
        """
        for request_data, response_data in content_iterator:
            # to do
            pass

    

    