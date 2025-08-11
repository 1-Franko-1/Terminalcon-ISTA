# -- file: web.py --
# -- libraries --
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
import requests
from urllib.parse import urlparse, urljoin
from urllib.robotparser import RobotFileParser
from requests.exceptions import RequestException
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
from urllib.parse import urlparse, parse_qs
from tqdm import tqdm
import json
import os
import warnings

# Filter XML parsing warning
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

google_api_key = os.getenv("GOOGLE_KEY")
google_cx = os.getenv("GOOGLE_CX")

def get_youtube_captions(url):
    try:
        query = urlparse(url).query
        video_id = parse_qs(query).get("v")

        if not video_id:
            return {"error": "Invalid YouTube URL."}

        video_id = video_id[0]

        try:
            transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['en'])
        except NoTranscriptFound:
            transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['en-US'])

        readable_text = "\n".join([entry['text'] for entry in transcript])
        return {"text": readable_text}

    except TranscriptsDisabled:
        return {"error": "Captions are disabled for this video."}
    except NoTranscriptFound:
        return {"error": "No captions available for this video."}
    except Exception as e:
        return {"error": f"Error: {str(e)}"}

class AdvCrawler:
    _robots_cache = {}

    def __init__(self, url, user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"):
        self.url = url
        self.user_agent = user_agent  # Fix: Define the user_agent attribute

    def crawl(self):
        """Main crawl method that respects robots.txt rules."""
        try:
            # Specialized handling for known platforms
            if "youtube.com" in self.url or "youtu.be" in self.url:
                return self._crawl_youtube()
            elif "twitter.com" in self.url:
                return self._crawl_twitter()
            elif "medium.com" in self.url:
                return self._crawl_medium()
            elif "github.com" in self.url:
                return self._crawl_github()
            elif "stackoverflow.com" in self.url:
                return self._crawl_stackoverflow()
            elif "news.ycombinator.com" in self.url:
                return self._crawl_hackernews()
            elif "dev.to" in self.url:
                return self._crawl_devto()
            elif "steampowered.com" in self.url:
                return self._crawl_steam()

            return self._crawl_general()

        except requests.exceptions.RequestException as e:
            return {"error": f"Error occurred while fetching the URL: {str(e)}"}
        except Exception as e:
            return {"error": f"An error occurred: {str(e)}"}

    def _get_headers(self):
        """Simulate a request from a popular browser."""
        return {"User-Agent": self.user_agent}  # Use instance attribute

    def _crawl_general(self):
        response = requests.get(self.url, timeout=10, headers=self._get_headers())

        if response.status_code != 200:
            return {"error": f"Failed to retrieve the content, status code: {response.status_code}"}

        soup = BeautifulSoup(response.content, "html.parser")

        # Extract the title
        title = soup.title.string.strip() if soup.title else "No title found"

        # Extract the meta description
        description_tag = soup.find("meta", attrs={"name": "description"})
        description = description_tag["content"].strip() if description_tag else "No description available"

        # Extract links
        all_links = [a["href"] for a in soup.find_all("a", href=True)]

        # Filter internal links
        base_url = "{0.scheme}://{0.netloc}".format(urlparse(self.url))
        internal_links = []
        for link in all_links:
            full_link = urljoin(base_url, link)
            if urlparse(full_link).netloc == urlparse(self.url).netloc:
                internal_links.append(full_link)

        # Take up to 3 internal links
        selected_links = internal_links[:3]

        clicked_pages = []

        for link in selected_links:
            try:
                sub_response = requests.get(link, timeout=10, headers=self._get_headers())
                if sub_response.status_code != 200:
                    continue

                sub_soup = BeautifulSoup(sub_response.content, "html.parser")
                sub_title = sub_soup.title.string.strip() if sub_soup.title else "No title found"
                sub_description_tag = sub_soup.find("meta", attrs={"name": "description"})
                sub_description = sub_description_tag["content"].strip() if sub_description_tag else "No description available"

                clicked_pages.append({
                    "link": link,
                    "title": sub_title,
                    "description": sub_description
                })
            except Exception as e:
                continue  # skip any errors in subpage fetching

        # Extract and limit site content to 100 words
        paragraphs = soup.find_all("p")
        full_text = " ".join(p.get_text(strip=True) for p in paragraphs)
        words = full_text.split()
        limited_text = " ".join(words[:100])

        return {
            "link": self.url,
            "title": title,
            "description": description,
            "scrape": limited_text,
            "clicked_pages": clicked_pages  # <-- Add clicked pages info here
        }

    def _crawl_youtube(self):
        response = requests.get(self.url, timeout=10)
        
        if response.status_code != 200:
            return {"error": f"Failed to retrieve the YouTube page, status code: {response.status_code}"}
        
        soup = BeautifulSoup(response.content, "html.parser")
        
        title = soup.title.string if soup.title else "No title found"
        description_meta = soup.find("meta", attrs={"name": "description"})
        description = description_meta["content"] if description_meta else "No description available"
        
        # Detect if URL is a channel or a video
        if "youtube.com/channel/" in self.url or "youtube.com/@" in self.url or "youtube.com/user/" in self.url:
            # Extract channel-specific metadata
            subscribers_text = None
            metadata_row = soup.find_all("div", class_="yt-content-metadata-view-model-wiz__metadata-row")
            
            for row in metadata_row:
                subscriber_text_element = row.find("span", class_="yt-core-attributed-string")
                if subscriber_text_element and "subskrybentów" or "subscribers" in subscriber_text_element.text:
                    subscribers_text = subscriber_text_element.text.strip()
                    break
            
            subscribers = subscribers_text if subscribers_text else "Subscriber count not available"
            
            return {
                "link": self.url,
                "title": title,
                "description": description,
                "subscribers": subscribers,
                "type": "channel"
            }
        
        # Extract video-specific metadata
        video_id = self.url.split("v=")[-1].split("&")[0] if "v=" in self.url else "No video ID found"
        channel_meta = soup.find("link", attrs={"itemprop": "name"})
        channel = channel_meta["content"] if channel_meta else "No channel information available"

        captions_result = get_youtube_captions(self.url)

        if "text" in captions_result:
            captions = captions_result["text"]
            captions = captions[:500] + "..." if len(captions) > 500 else captions
        else:
            captions = captions_result["error"]

        return {
            "link": self.url,
            "title": title,
            "description": description,
            "video_id": video_id,
            "channel": channel,
            "captions": captions,
            "type": "video"
        }

    def _crawl_twitter(self):
        response = requests.get(self.url, timeout=10)

        if response.status_code != 200:
            return "Failed to retrieve the Twitter page, status code: {}".format(response.status_code)

        soup = BeautifulSoup(response.content, "html.parser")

        title = soup.title.string if soup.title else "No title found"

        # Extract Twitter-specific metadata, like tweets and user handle
        description = soup.find("meta", attrs={"name": "description"})
        description = description["content"] if description else "No description available"

        return {
            "link": self.url,
            "title": title,
            "description": description
        }

    def _crawl_medium(self):
        response = requests.get(self.url, timeout=10)

        if response.status_code != 200:
            return "Failed to retrieve the Medium page, status code: {}".format(response.status_code)

        soup = BeautifulSoup(response.content, "html.parser")

        title = soup.title.string if soup.title else "No title found"

        # Extract Medium-specific metadata, like article author and reading time
        author = soup.find("meta", attrs={"name": "author"})
        author = author["content"] if author else "No author information available"

        return {
            "link": self.url,
            "title": title,
            "author": author
        }
    
    def _crawl_github(self):
        response = requests.get(self.url, timeout=10)
        if response.status_code != 200:
            return "Failed to retrieve the GitHub page, status code: {}".format(response.status_code)

        soup = BeautifulSoup(response.content, "html.parser")
        repo_name = soup.find("strong", class_="mr-2").text.strip() if soup.find("strong", class_="mr-2") else "No repository name found"
        description = soup.find("span", class_="text-gray").text.strip() if soup.find("span", class_="text-gray") else "No description available"
        stars = soup.find("a", class_="social-count js-social-count").text.strip() if soup.find("a", class_="social-count js-social-count") else "No stars count"

        return {
            "link": self.url,
            "repo_name": repo_name,
            "description": description,
            "stars": stars
        }

    def _crawl_stackoverflow(self):
        response = requests.get(self.url, timeout=10)
        if response.status_code != 200:
            return "Failed to retrieve the Stack Overflow page, status code: {}".format(response.status_code)

        soup = BeautifulSoup(response.content, "html.parser")
        title = soup.title.string if soup.title else "No title found"
        question = soup.find("div", class_="post-text").text.strip() if soup.find("div", class_="post-text") else "No question content"
        tags = [tag.text for tag in soup.find_all("a", class_="post-tag")]  # Extract tags for the question

        return {
            "link": self.url,
            "title": title,
            "question": question,
            "tags": tags
        }

    def _crawl_hackernews(self):
        response = requests.get(self.url, timeout=10)
        if response.status_code != 200:
            return "Failed to retrieve the Hacker News page, status code: {}".format(response.status_code)

        soup = BeautifulSoup(response.content, "html.parser")
        title = soup.title.string if soup.title else "No title found"
        comments = soup.find("a", class_="hnuser").text if soup.find("a", class_="hnuser") else "No comments available"

        return {
            "link": self.url,
            "title": title,
            "comments": comments
        }

    def _crawl_devto(self):
        response = requests.get(self.url, timeout=10)
        if response.status_code != 200:
            return "Failed to retrieve the Dev.to page, status code: {}".format(response.status_code)

        soup = BeautifulSoup(response.content, "html.parser")
        title = soup.title.string if soup.title else "No title found"
        author = soup.find("a", class_="crayons-link").text if soup.find("a", class_="crayons-link") else "No author found"
        reading_time = soup.find("div", class_="crayons-story__time").text.strip() if soup.find("div", class_="crayons-story__time") else "No reading time available"

        return {
            "link": self.url,
            "title": title,
            "author": author,
            "reading_time": reading_time
        }

    def _crawl_steam(self):
        headers = self._get_headers()
        response = requests.get(self.url, timeout=10, headers=headers)
        if response.status_code != 200:
            return f"Failed to retrieve the Steam page, status code: {response.status_code}"

        soup = BeautifulSoup(response.content, "html.parser")
        title = soup.find("div", class_="apphub_AppName").text.strip() if soup.find("div", class_="apphub_AppName") else "No title found"
        description = soup.find("div", class_="game_description_snippet").text.strip() if soup.find("div", class_="game_description_snippet") else "No description available"
        release_date = soup.find("div", class_="date").text.strip() if soup.find("div", class_="date") else "No release date available"
        developer = soup.find("div", class_="dev_row").find("a").text.strip() if soup.find("div", class_="dev_row") else "No developer found"
        publisher = soup.find("div", class_="dev_row").find_all("a")[1].text.strip() if soup.find("div", class_="dev_row") and len(soup.find("div", class_="dev_row").find_all("a")) > 1 else "No publisher found"

        return {
            "link": self.url,
            "title": title,
            "description": description,
            "release_date": release_date,
            "developer": developer,
            "publisher": publisher
        }

async def web_search(tool_input: str, num_sites: int) -> str:
    """Perform a web search and return the top results with links. Retries up to 3 times if no results."""
    search_results = []

    try:
        num_sites = int(num_sites)  # Ensure it's an integer

        if 'http://' in tool_input or 'https://' in tool_input:
            # Directly crawl a provided URL
            with tqdm(total=1, desc="Crawling URL", unit="site", 
                     bar_format="\033[94m{desc}\033[0m: {percentage:3.0f}%|"
                     "\033[92m{bar}\033[0m| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]") as pbar:
                crawler = AdvCrawler(tool_input)
                scraped_result = crawler.crawl()
                search_results.append({"link": tool_input, "scraped_content": scraped_result})
                pbar.update(1)
        else:
            max_retries = 3
            for attempt in range(max_retries):
                search_url = (
                    f"https://www.googleapis.com/customsearch/v1"
                    f"?q={tool_input}"
                    f"&key={google_api_key}"
                    f"&cx={google_cx}"
                )

                response = requests.get(search_url)
                response.raise_for_status()

                response_json = response.json()
                items = response_json.get("items", [])

                if items:
                    with tqdm(total=min(num_sites, len(items)), desc="Crawling search results", unit="site",
                            bar_format="\033[94m{desc}\033[0m: {percentage:3.0f}%|"
                            "\033[92m{bar}\033[0m| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]") as pbar:
                        for item in items[:num_sites]:
                            link = item.get("link")
                            crawler = AdvCrawler(link)
                            search_results.append({
                                "title": item.get("title"),
                                "link": link,
                                "snippet": item.get("snippet"),
                                "scraped_content": crawler.crawl()
                            })
                            pbar.update(1)
                    break
                else:
                    print(f"No results found, attempt {attempt + 1} of {max_retries}...")

            if not search_results:
                return json.dumps({"error": "No search results after 3 attempts."}, indent=4)

    except requests.RequestException as e:
        return json.dumps({"error": str(e)}, indent=4)

    except Exception as e:
        return json.dumps({"error": str(e)}, indent=4)

    return json.dumps(search_results, indent=4)