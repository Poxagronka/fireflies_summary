"""Fireflies API client for fetching meeting transcripts."""

import logging
import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import aiohttp
import json
from dataclasses import dataclass

from .config import config

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
    
    async def get_transcripts(self, limit: int = 20) -> List[Transcript]:
        """Get recent transcripts."""
        query = """
        query GetTranscripts($limit: Int!) {
            transcripts(limit: $limit) {
                id
                title
                date
                duration
                participants
                summary {
                    overview
                    action_items
                    keywords
                    outline
                }
                sentences {
                    text
                    speaker_name
                }
                meeting_attendees {
                    displayName
                    email
                }
            }
        }
        """
        
        try:
            data = await self._make_request(query, {"limit": limit})
            transcripts = []
            
            for item in data.get("transcripts", []):
                transcript = self._parse_transcript(item)
                if transcript:
                    transcripts.append(transcript)
            
            return transcripts
        except Exception as e:
            logger.error(f"Failed to get transcripts: {str(e)}")
            return []
    
    async def get_transcript_by_id(self, transcript_id: str) -> Optional[Transcript]:
        """Get a specific transcript by ID."""
        query = """
        query GetTranscript($id: String!) {
            transcript(id: $id) {
                id
                title
                date
                duration
                participants
                summary {
                    overview
                    action_items
                    keywords
                    outline
                }
                sentences {
                    text
                    speaker_name
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
        limit: int = 10
    ) -> List[Transcript]:
        """Search transcripts based on criteria."""
        query = """
        query SearchTranscripts($limit: Int!, $filters: TranscriptFilters) {
            transcripts(limit: $limit, filters: $filters) {
                id
                title
                date
                duration
                participants
                summary {
                    overview
                    action_items
                    keywords
                    outline
                }
                meeting_attendees {
                    displayName
                    email
                }
            }
        }
        """
        
        filters = {}
        if title_pattern:
            filters["title"] = title_pattern
        if start_date:
            filters["start_date"] = start_date.isoformat()
        if end_date:
            filters["end_date"] = end_date.isoformat()
        
        try:
            data = await self._make_request(
                query,
                {"limit": limit, "filters": filters}
            )
            transcripts = []
            
            for item in data.get("transcripts", []):
                transcript = self._parse_transcript(item)
                if transcript:
                    transcripts.append(transcript)
            
            return transcripts
        except Exception as e:
            logger.error(f"Failed to search transcripts: {str(e)}")
            return []
    
    async def find_previous_meeting_in_series(
        self,
        meeting_title: str,
        meeting_date: datetime
    ) -> Optional[Transcript]:
        """Find the most recent previous meeting in the same series."""
        # Search for meetings with similar titles before the given date
        start_date = meeting_date - timedelta(days=30)  # Look back 30 days
        
        transcripts = await self.search_transcripts(
            title_pattern=meeting_title,
            start_date=start_date,
            end_date=meeting_date,
            limit=5
        )
        
        # Filter to only meetings before the target date
        previous_meetings = [
            t for t in transcripts
            if t.date < meeting_date
        ]
        
        # Sort by date and return the most recent
        if previous_meetings:
            previous_meetings.sort(key=lambda x: x.date, reverse=True)
            return previous_meetings[0]
        
        return None
    
    def _parse_transcript(self, data: Dict[str, Any]) -> Optional[Transcript]:
        """Parse transcript data from API response."""
        try:
            # Parse date
            date_str = data.get("date", "")
            if date_str:
                date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            else:
                date = datetime.now()
            
            # Parse summary
            summary_data = data.get("summary", {})
            summary = summary_data.get("overview", "")
            action_items = summary_data.get("action_items", [])
            if isinstance(action_items, str):
                action_items = [action_items] if action_items else []
            
            key_topics = summary_data.get("keywords", [])
            if isinstance(key_topics, str):
                key_topics = [key_topics] if key_topics else []
            
            # Parse participants
            attendees = data.get("meeting_attendees", [])
            participants = [
                a.get("displayName", a.get("email", "Unknown"))
                for a in attendees
            ]
            
            # Parse transcript text
            sentences = data.get("sentences", [])
            transcript_text = "\n".join([
                f"{s.get('speaker_name', 'Unknown')}: {s.get('text', '')}"
                for s in sentences[:100]  # Limit to first 100 sentences
            ])
            
            return Transcript(
                id=data.get("id", ""),
                title=data.get("title", "Untitled Meeting"),
                date=date,
                duration_minutes=data.get("duration", 0) // 60,
                summary=summary,
                action_items=action_items,
                participants=participants,
                meeting_url=data.get("meeting_url"),
                transcript_text=transcript_text,
                key_topics=key_topics
            )
        except Exception as e:
            logger.error(f"Failed to parse transcript: {str(e)}")
            return None