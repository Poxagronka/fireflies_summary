"""Meeting analyzer for identifying series and patterns."""

import re
import logging
from typing import List, Dict, Optional, Set, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class MeetingSeries:
    """Represents a series of related meetings."""
    series_id: str
    series_name: str
    pattern: str  # daily, weekly, biweekly, monthly, adhoc
    meetings: List[Dict]
    common_participants: Set[str]
    common_keywords: Set[str]


class MeetingAnalyzer:
    """Analyzer for identifying meeting series and patterns."""
    
    # Common meeting series patterns
    SERIES_PATTERNS = [
        (r"daily\s+(standup|sync|scrum|meeting)", "daily"),
        (r"weekly\s+(\w+\s*)*(meeting|sync|review|retro|retrospective)", "weekly"),
        (r"bi-?weekly\s+(\w+\s*)*(meeting|sync|review)", "biweekly"),
        (r"monthly\s+(\w+\s*)*(meeting|sync|review|all-hands)", "monthly"),
        (r"1:1|one-on-one|1-on-1", "weekly"),
        (r"sprint\s+(planning|review|retro|retrospective)", "biweekly"),
        (r"(team|dept|department)\s+(meeting|sync|standup)", "weekly"),
        (r"(product|design|engineering)\s+(review|sync|meeting)", "weekly"),
        (r"all-hands|company\s+meeting|town\s+hall", "monthly"),
    ]
    
    # Common series identifiers
    SERIES_IDENTIFIERS = [
        r"\[(.+?)\]",  # [Series Name]
        r"\((.+?)\)",  # (Series Name)
        r"^(.+?):",    # Series Name:
        r"^(.+?)\s*-", # Series Name -
        r"^(.+?)\s*\|", # Series Name |
    ]
    
    def __init__(self):
        self.series_cache: Dict[str, MeetingSeries] = {}
    
    def identify_series(self, meetings: List[Dict]) -> List[MeetingSeries]:
        """Group meetings into series based on patterns."""
        series_map = defaultdict(list)
        
        for meeting in meetings:
            series_key = self.extract_series_key(meeting)
            series_map[series_key].append(meeting)
        
        # Convert to MeetingSeries objects
        series_list = []
        for series_key, series_meetings in series_map.items():
            if len(series_meetings) >= 2:  # Only consider as series if 2+ meetings
                series = self._create_series(series_key, series_meetings)
                if series:
                    series_list.append(series)
                    self.series_cache[series.series_id] = series
        
        return series_list
    
    def extract_series_key(self, meeting: Dict) -> str:
        """Extract a key that identifies the meeting series."""
        title = meeting.get("title", "").lower().strip()
        
        # Try to extract series name from common patterns
        series_name = self.extract_series_name(title)
        if series_name:
            return self._normalize_series_key(series_name)
        
        # Fall back to removing date/time patterns
        cleaned_title = self._remove_date_time_patterns(title)
        return self._normalize_series_key(cleaned_title)
    
    def extract_series_name(self, title: str) -> Optional[str]:
        """Extract the series name from a meeting title."""
        title_lower = title.lower().strip()
        
        # Check for explicit series identifiers
        for pattern in self.SERIES_IDENTIFIERS:
            match = re.search(pattern, title, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        
        # Check for known series patterns
        for pattern, _ in self.SERIES_PATTERNS:
            match = re.search(pattern, title_lower)
            if match:
                return match.group(0).strip()
        
        # Try to extract base name by removing common suffixes
        base_name = re.sub(
            r"(\s+\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\s+\d{4}[/-]\d{1,2}[/-]\d{1,2}|\s+\#\d+|\s+\(\d+\)|\s+\d{1,2}:\d{2})",
            "",
            title_lower
        ).strip()
        
        if base_name and len(base_name) > 5:
            return base_name
        
        return None
    
    def find_previous_in_series(
        self,
        meeting_title: str,
        meeting_date: datetime,
        all_meetings: List[Dict]
    ) -> Optional[Dict]:
        """Find the most recent previous meeting in the same series."""
        series_key = self.extract_series_key({"title": meeting_title})
        
        # Find all meetings with the same series key
        series_meetings = []
        for meeting in all_meetings:
            if self.extract_series_key(meeting) == series_key:
                meeting_datetime = meeting.get("date")
                if isinstance(meeting_datetime, str):
                    meeting_datetime = datetime.fromisoformat(meeting_datetime.replace("Z", "+00:00"))
                
                if meeting_datetime and meeting_datetime < meeting_date:
                    series_meetings.append(meeting)
        
        # Sort by date and return the most recent
        if series_meetings:
            series_meetings.sort(
                key=lambda x: datetime.fromisoformat(x["date"].replace("Z", "+00:00"))
                if isinstance(x["date"], str) else x["date"],
                reverse=True
            )
            return series_meetings[0]
        
        return None
    
    def detect_meeting_pattern(self, meetings: List[Dict]) -> str:
        """Detect the recurrence pattern of a meeting series."""
        if len(meetings) < 2:
            return "adhoc"
        
        # Sort meetings by date
        sorted_meetings = sorted(
            meetings,
            key=lambda x: datetime.fromisoformat(x["date"].replace("Z", "+00:00"))
            if isinstance(x["date"], str) else x["date"]
        )
        
        # Calculate intervals between meetings
        intervals = []
        for i in range(1, len(sorted_meetings)):
            date1 = sorted_meetings[i-1]["date"]
            date2 = sorted_meetings[i]["date"]
            
            if isinstance(date1, str):
                date1 = datetime.fromisoformat(date1.replace("Z", "+00:00"))
            if isinstance(date2, str):
                date2 = datetime.fromisoformat(date2.replace("Z", "+00:00"))
            
            interval = (date2 - date1).days
            intervals.append(interval)
        
        if not intervals:
            return "adhoc"
        
        # Determine pattern based on average interval
        avg_interval = sum(intervals) / len(intervals)
        
        if avg_interval <= 1.5:
            return "daily"
        elif 5 <= avg_interval <= 9:
            return "weekly"
        elif 12 <= avg_interval <= 16:
            return "biweekly"
        elif 25 <= avg_interval <= 35:
            return "monthly"
        else:
            return "adhoc"
    
    def get_common_participants(self, meetings: List[Dict]) -> Set[str]:
        """Get participants that appear in most meetings of a series."""
        participant_counts = defaultdict(int)
        
        for meeting in meetings:
            participants = meeting.get("participants", [])
            for participant in participants:
                participant_counts[participant] += 1
        
        # Return participants that appear in at least 50% of meetings
        threshold = len(meetings) * 0.5
        common = {
            p for p, count in participant_counts.items()
            if count >= threshold
        }
        
        return common
    
    def get_common_keywords(self, meetings: List[Dict]) -> Set[str]:
        """Extract common keywords from meeting summaries."""
        keyword_counts = defaultdict(int)
        
        for meeting in meetings:
            keywords = meeting.get("keywords", [])
            for keyword in keywords:
                keyword_counts[keyword.lower()] += 1
        
        # Return keywords that appear in at least 30% of meetings
        threshold = len(meetings) * 0.3
        common = {
            k for k, count in keyword_counts.items()
            if count >= threshold and len(k) > 3
        }
        
        return common
    
    def _create_series(self, series_key: str, meetings: List[Dict]) -> Optional[MeetingSeries]:
        """Create a MeetingSeries object from grouped meetings."""
        if not meetings:
            return None
        
        # Determine series name
        series_name = series_key
        for meeting in meetings:
            extracted_name = self.extract_series_name(meeting.get("title", ""))
            if extracted_name:
                series_name = extracted_name
                break
        
        # Detect pattern
        pattern = self.detect_meeting_pattern(meetings)
        
        # Get common elements
        common_participants = self.get_common_participants(meetings)
        common_keywords = self.get_common_keywords(meetings)
        
        return MeetingSeries(
            series_id=series_key,
            series_name=series_name,
            pattern=pattern,
            meetings=meetings,
            common_participants=common_participants,
            common_keywords=common_keywords
        )
    
    def _normalize_series_key(self, text: str) -> str:
        """Normalize text to create a consistent series key."""
        # Remove special characters and extra spaces
        normalized = re.sub(r"[^\w\s-]", "", text.lower())
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized
    
    def _remove_date_time_patterns(self, text: str) -> str:
        """Remove date and time patterns from text."""
        patterns = [
            r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}",  # MM/DD/YYYY or MM-DD-YYYY
            r"\d{4}[/-]\d{1,2}[/-]\d{1,2}",    # YYYY-MM-DD
            r"\d{1,2}:\d{2}(\s*(am|pm))?",     # Time
            r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}",  # Month DD
            r"\#\d+",                           # Issue numbers
            r"\(\d+\)",                         # Numbers in parentheses
            r"week\s+\d+",                      # Week numbers
            r"q[1-4]\s+\d{4}",                  # Quarter and year
        ]
        
        result = text
        for pattern in patterns:
            result = re.sub(pattern, "", result, flags=re.IGNORECASE)
        
        return re.sub(r"\s+", " ", result).strip()