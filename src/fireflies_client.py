"""Fireflies API client for fetching meeting transcripts."""

import logging
import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import aiohttp
import json
from dataclasses import dataclass

try:
    from .config import config
except ImportError:
    # Fallback for standalone testing
    import os
    class Config:
        def __init__(self):
            self.FIREFLIES_API_URL = "https://api.fireflies.ai/graphql"
            self.FIREFLIES_API_KEY = os.getenv('FIREFLIES_API_KEY')
    config = Config()

logger = logging.getLogger(__name__)


@dataclass
class Transcript:
    """Represents a Fireflies transcript."""
    id: str
    title: str
    date: datetime
    duration_minutes: int
    summary: Optional[str]
    action_items: List[str]
    participants: List[str]
    meeting_url: Optional[str]
    transcript_text: Optional[str]
    key_topics: List[str]


class FirefliesClient:
    """Client for interacting with Fireflies API."""
    
    def __init__(self):
        self.api_key = config.FIREFLIES_API_KEY
        self.api_url = config.FIREFLIES_API_URL
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        """Async context manager entry."""
        self.session = aiohttp.ClientSession(headers=self.headers)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.session:
            await self.session.close()
    
    async def _make_request(self, query: str, variables: Optional[Dict] = None) -> Dict:
        """Make a GraphQL request to Fireflies API."""
        if not self.session:
            self.session = aiohttp.ClientSession(headers=self.headers)
        
        payload = {
            "query": query,
            "variables": variables or {}
        }
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with self.session.post(
                    self.api_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        if "errors" in data:
                            logger.error(f"GraphQL errors: {data['errors']}")
                            raise Exception(f"GraphQL errors: {data['errors']}")
                        return data.get("data", {})
                    else:
                        text = await response.text()
                        logger.error(f"API request failed with status {response.status}: {text}")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(2 ** attempt)
                        else:
                            raise Exception(f"API request failed: {text}")
            except asyncio.TimeoutError:
                logger.error(f"Request timeout on attempt {attempt + 1}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise
            except Exception as e:
                logger.error(f"Request error on attempt {attempt + 1}: {str(e)}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise
        
        return {}
    
    async def get_transcripts(self, limit: int = 20, include_shared: bool = True) -> List[Transcript]:
        """Get recent transcripts including both my meetings and shared meetings."""
        all_transcripts = []
        
        # First, get my meetings (mine=true)
        try:
            my_transcripts = await self._get_transcripts_with_filter(limit, mine=True)
            all_transcripts.extend(my_transcripts)
            logger.info(f"Found {len(my_transcripts)} transcripts in 'my meetings'")
        except Exception as e:
            logger.error(f"Failed to get my transcripts: {e}")
        
        # Then get all transcripts (including shared) without mine filter
        if include_shared:
            try:
                all_available = await self._get_transcripts_with_filter(limit * 2, mine=None)
                # Filter out transcripts we already have from "my meetings"
                my_ids = {t.id for t in my_transcripts} if 'my_transcripts' in locals() else set()
                shared_transcripts = [t for t in all_available if t.id not in my_ids]
                all_transcripts.extend(shared_transcripts)
                logger.info(f"Found {len(shared_transcripts)} additional shared transcripts")
            except Exception as e:
                logger.error(f"Failed to get shared transcripts: {e}")
        
        # Remove duplicates and sort by date
        seen_ids = set()
        unique_transcripts = []
        for transcript in all_transcripts:
            if transcript.id not in seen_ids:
                unique_transcripts.append(transcript)
                seen_ids.add(transcript.id)
        
        # Sort by date (most recent first) and limit results
        unique_transcripts.sort(key=lambda x: x.date, reverse=True)
        return unique_transcripts[:limit]
    
    async def _get_transcripts_with_filter(self, limit: int, mine: Optional[bool] = None) -> List[Transcript]:
        """Get transcripts with optional mine filter."""
        query = """
        query GetTranscripts($limit: Int!, $mine: Boolean) {
            transcripts(limit: $limit, mine: $mine) {
                id
                title
                dateString
                duration
                summary {
                    overview
                    action_items
                    keywords
                }
                speakers {
                    id
                    name
                }
                meeting_attendees {
                    displayName
                    email
                }
            }
        }
        """
        
        variables = {"limit": min(limit, 50)}  # Max 50 per API docs
        if mine is not None:
            variables["mine"] = mine
        
        data = await self._make_request(query, variables)
        transcripts = []
        
        for item in data.get("transcripts", []):
            transcript = self._parse_transcript(item)
            if transcript:
                transcripts.append(transcript)
        
        return transcripts
    
    async def get_transcript_by_id(self, transcript_id: str) -> Optional[Transcript]:
        """Get a specific transcript by ID."""
        query = """
        query GetTranscript($id: String!) {
            transcript(id: $id) {
                id
                title
                dateString
                duration
                summary {
                    overview
                    action_items
                    keywords
                }
                speakers {
                    id
                    name
                }
                meeting_attendees {
                    displayName
                    email
                }
            }
        }
        """
        
        try:
            data = await self._make_request(query, {"id": transcript_id})
            transcript_data = data.get("transcript")
            if transcript_data:
                return self._parse_transcript(transcript_data)
            return None
        except Exception as e:
            logger.error(f"Failed to get transcript {transcript_id}: {str(e)}")
            return None
    
    async def search_transcripts(
        self,
        title_pattern: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 10,
        include_shared: bool = True
    ) -> List[Transcript]:
        """Search transcripts using Fireflies API parameters."""
        query = """
        query SearchTranscripts($limit: Int!, $keyword: String, $mine: Boolean) {
            transcripts(limit: $limit, keyword: $keyword, mine: $mine) {
                id
                title
                dateString
                duration
                summary {
                    overview
                    action_items
                    keywords
                }
                speakers {
                    id
                    name
                }
                meeting_attendees {
                    displayName
                    email
                }
            }
        }
        """
        
        all_results = []
        
        # Build base variables - remove date filtering for now as it's causing issues
        variables = {"limit": min(limit * 2, 50)}  # Max 50, get more to account for filtering
        
        if title_pattern:
            variables["keyword"] = title_pattern
        
        # Search in my meetings first
        try:
            variables["mine"] = True
            data = await self._make_request(query, variables)
            my_results = []
            for item in data.get("transcripts", []):
                transcript = self._parse_transcript(item)
                if transcript:
                    my_results.append(transcript)
            all_results.extend(my_results)
            logger.info(f"Found {len(my_results)} matching transcripts in 'my meetings'")
        except Exception as e:
            logger.error(f"Failed to search my transcripts: {e}")
        
        # Then search all transcripts (including shared) if requested
        if include_shared:
            try:
                variables_all = variables.copy()
                variables_all.pop("mine", None)  # Remove mine filter to get all transcripts
                data = await self._make_request(query, variables_all)
                shared_results = []
                my_ids = {t.id for t in all_results}  # Already found transcripts
                for item in data.get("transcripts", []):
                    transcript = self._parse_transcript(item)
                    if transcript and transcript.id not in my_ids:
                        shared_results.append(transcript)
                all_results.extend(shared_results)
                logger.info(f"Found {len(shared_results)} additional shared transcripts")
            except Exception as e:
                logger.error(f"Failed to search shared transcripts: {e}")
        
        # Sort by date (most recent first) and limit results
        all_results.sort(key=lambda x: x.date, reverse=True)
        return all_results[:limit]
    
    async def find_previous_meeting_in_series(
        self,
        meeting_title: str,
        meeting_date: datetime
    ) -> Optional[Transcript]:
        """Find the most recent previous meeting in the same series."""
        import pytz
        from datetime import timezone
        
        # Convert to Warsaw timezone for better matching
        warsaw_tz = pytz.timezone('Europe/Warsaw')
        
        # Ensure meeting_date is timezone-aware
        if meeting_date.tzinfo is None:
            # Assume input is in Warsaw time if no timezone specified
            meeting_date = warsaw_tz.localize(meeting_date)
        else:
            # Convert to Warsaw timezone for comparison
            meeting_date = meeting_date.astimezone(warsaw_tz)
        
        logger.info(f"Searching for previous meeting similar to '{meeting_title}' before {meeting_date} (Warsaw time)")
        
        try:
            # Direct minimal approach - just get basic transcripts without complex filtering
            query = """
            query GetBasicTranscripts($limit: Int!) {
                transcripts(limit: $limit) {
                    id
                    title
                    dateString
                    summary {
                        overview
                    }
                }
            }
            """
            
            data = await self._make_request(query, {"limit": 20})
            logger.info(f"Retrieved {len(data.get('transcripts', []))} basic transcripts")
            
            # Find matching meetings  
            candidates = []
            for item in data.get("transcripts", []):
                try:
                    title = item.get("title", "")
                    date_str = item.get("dateString", "")
                    
                    if not date_str:
                        continue
                    
                    # Parse date and convert to Warsaw timezone
                    transcript_date = self._parse_date_string(date_str)
                    if not transcript_date:
                        continue
                    
                    # Convert transcript date to Warsaw timezone for comparison
                    if transcript_date.tzinfo is None:
                        transcript_date = transcript_date.replace(tzinfo=timezone.utc)
                    transcript_date_warsaw = transcript_date.astimezone(warsaw_tz)
                    
                    if transcript_date_warsaw >= meeting_date:
                        continue
                    
                    # Simple title matching
                    if (title.lower() == meeting_title.lower() or
                        self._simple_title_match(meeting_title, title)):
                        
                        # Create minimal transcript
                        transcript = Transcript(
                            id=item.get("id", ""),
                            title=title,
                            date=transcript_date,
                            duration_minutes=0,
                            summary=item.get("summary", {}).get("overview", ""),
                            action_items=[],
                            participants=[],
                            meeting_url="",
                            transcript_text="",
                            key_topics=[]
                        )
                        candidates.append(transcript)
                        logger.info(f"Found candidate: {title} ({transcript_date})")
                        
                except Exception as e:
                    logger.error(f"Error parsing transcript item: {e}")
                    continue
            
            if candidates:
                # Sort by date and return the most recent
                candidates.sort(key=lambda x: x.date, reverse=True)
                best_match = candidates[0]
                logger.info(f"Selected best match: {best_match.title} from {best_match.date}")
                return best_match
            
            logger.info("No matching previous meetings found")
            return None
            
        except Exception as e:
            logger.error(f"Error in find_previous_meeting_in_series: {e}")
            return None
    
    def _parse_date_string(self, date_str: str) -> Optional[datetime]:
        """Parse dateString from Fireflies API."""
        try:
            from datetime import timezone
            # Try ISO format first
            if 'T' in date_str and date_str.endswith('Z'):
                return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            elif 'T' in date_str:
                # Try without timezone, then add UTC
                dt = datetime.fromisoformat(date_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            return None
        except:
            return None
    
    def _simple_title_match(self, title1: str, title2: str) -> bool:
        """Very simple title matching."""
        t1 = title1.lower().strip()
        t2 = title2.lower().strip()
        
        # Check if they share significant words
        words1 = set(t1.replace('/', ' ').split())
        words2 = set(t2.replace('/', ' ').split())
        
        if len(words1) < 2 or len(words2) < 2:
            return False
        
        common = words1.intersection(words2)
        return len(common) >= 2  # At least 2 common words
    
    async def _simple_keyword_search(self, keyword: str, limit: int = 20) -> List[Transcript]:
        """Simple keyword search without complex filtering."""
        query = """
        query SearchByKeyword($limit: Int!, $keyword: String!) {
            transcripts(limit: $limit, keyword: $keyword) {
                id
                title
                dateString
                duration
                summary {
                    overview
                    action_items
                    keywords
                }
                speakers {
                    id
                    name
                }
                meeting_attendees {
                    displayName
                    email
                }
            }
        }
        """
        
        try:
            data = await self._make_request(query, {"limit": min(limit, 50), "keyword": keyword})
            results = []
            
            for item in data.get("transcripts", []):
                transcript = self._parse_transcript(item)
                if transcript:
                    results.append(transcript)
            
            logger.info(f"Simple keyword search for '{keyword}' found {len(results)} results")
            return results
            
        except Exception as e:
            logger.error(f"Simple keyword search failed: {e}")
            return []
    
    def _extract_key_words(self, title: str) -> List[str]:
        """Extract key search words from meeting title."""
        # Remove common words and extract meaningful terms
        ignore_words = {'meeting', 'call', 'sync', 'standup', 'weekly', 'daily', 'monthly', 
                       'review', 'check-in', 'update', 'session', 'the', 'and', 'or', 'with', '/'}
        
        words = title.replace('/', ' ').replace('-', ' ').replace('_', ' ').split()
        key_words = []
        
        for word in words:
            clean_word = word.strip('()[]{}.,!?-_').lower()
            if clean_word and clean_word not in ignore_words and len(clean_word) > 2:
                key_words.append(clean_word)
        
        # Return most specific words first
        key_words.sort(key=len, reverse=True)
        return key_words[:3]  # Top 3 most specific words
    
    def _titles_match(self, title1: str, title2: str) -> bool:
        """Simple title matching logic."""
        t1 = title1.lower().strip()
        t2 = title2.lower().strip()
        
        # Exact match
        if t1 == t2:
            return True
        
        # Contains significant common words (more than 70% overlap)
        words1 = set(t1.replace('/', ' ').split())
        words2 = set(t2.replace('/', ' ').split())
        
        if not words1 or not words2:
            return False
        
        common = words1.intersection(words2)
        min_words = min(len(words1), len(words2))
        
        if min_words == 0:
            return False
        
        overlap = len(common) / min_words
        return overlap >= 0.7
    
    def _is_similar_meeting(self, title1: str, title2: str) -> bool:
        """Check if two meeting titles are similar (same series)."""
        # Normalize titles
        t1 = title1.lower().strip()
        t2 = title2.lower().strip()
        
        # Extract key words (ignore common meeting words)
        ignore_words = {'meeting', 'call', 'sync', 'standup', 'weekly', 'daily', 'monthly', 
                       'review', 'check-in', 'update', 'session', 'the', 'and', 'or', 'with'}
        
        def extract_key_words(title):
            words = set(word.strip('()[]{}.,!?-_') for word in title.split())
            return words - ignore_words
        
        key_words1 = extract_key_words(t1)
        key_words2 = extract_key_words(t2)
        
        if not key_words1 or not key_words2:
            return False
        
        # Calculate overlap - at least 70% of words should match
        overlap = key_words1.intersection(key_words2)
        min_words = min(len(key_words1), len(key_words2))
        
        if min_words == 0:
            return False
        
        similarity = len(overlap) / min_words
        logger.debug(f"Similarity between '{title1}' and '{title2}': {similarity:.2f}")
        
        return similarity >= 0.7
    
    def _parse_transcript(self, data: Dict[str, Any]) -> Optional[Transcript]:
        """Parse transcript data from API response."""
        try:
            # Parse date from dateString field (format: "Mon Feb 19 2024 18:37:09 GMT+0000 (UTC)")
            date_str = data.get("dateString", "")
            if date_str:
                try:
                    # Try to parse the dateString format
                    from datetime import datetime
                    import re
                    # Extract ISO-like components from the string
                    # Example: "Mon Feb 19 2024 18:37:09 GMT+0000 (UTC)"
                    match = re.search(r'(\w+)\s+(\w+)\s+(\d+)\s+(\d+)\s+(\d+):(\d+):(\d+)', date_str)
                    if match:
                        # Create a simplified date from the extracted parts
                        month_map = {
                            'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
                            'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12
                        }
                        _, month_str, day, year, hour, minute, second = match.groups()
                        month = month_map.get(month_str, 1)
                        date = datetime(int(year), month, int(day), int(hour), int(minute), int(second))
                    else:
                        date = datetime.now()
                except:
                    date = datetime.now()
            else:
                date = datetime.now()
            
            # Parse summary
            summary_data = data.get("summary", {})
            summary = summary_data.get("overview", "") if summary_data else ""
            
            # Parse action items
            action_items = summary_data.get("action_items", []) if summary_data else []
            if isinstance(action_items, str):
                # Split string action items by common separators
                action_items = [item.strip() for item in action_items.split('\n') if item.strip()] if action_items else []
            elif not isinstance(action_items, list):
                action_items = []
            
            # Parse keywords/topics
            key_topics = summary_data.get("keywords", []) if summary_data else []
            if isinstance(key_topics, str):
                key_topics = [topic.strip() for topic in key_topics.split(',') if topic.strip()] if key_topics else []
            elif not isinstance(key_topics, list):
                key_topics = []
            
            # Parse participants from speakers and meeting_attendees
            participants = []
            
            # From speakers
            speakers = data.get("speakers", [])
            for speaker in speakers:
                name = speaker.get("name", "").strip()
                if name and name not in participants:
                    participants.append(name)
            
            # From meeting attendees (fallback)
            if not participants:
                attendees = data.get("meeting_attendees", [])
                for attendee in attendees:
                    name = attendee.get("displayName") or attendee.get("email") or "Unknown"
                    if name and name not in participants:
                        participants.append(name)
            
            # Duration in minutes
            duration_minutes = data.get("duration", 0)
            if duration_minutes > 3600:  # If it's in seconds, convert to minutes
                duration_minutes = duration_minutes // 60
            
            return Transcript(
                id=data.get("id", ""),
                title=data.get("title", "Untitled Meeting"),
                date=date,
                duration_minutes=duration_minutes,
                summary=summary,
                action_items=action_items,
                participants=participants,
                meeting_url=data.get("meeting_url"),
                transcript_text="",  # Not loading full transcript for performance
                key_topics=key_topics
            )
        except Exception as e:
            logger.error(f"Failed to parse transcript {data.get('id', 'unknown')}: {str(e)}")
            return None