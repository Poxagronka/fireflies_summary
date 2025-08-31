"""
Working Calendar API Integration Test
Tests the actual integration with timezone-aware datetime handling
"""

import requests
import asyncio
import aiohttp
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class WorkingCalendarClient:
    def __init__(self):
        self.api_url = "https://script.google.com/macros/s/AKfycbx3xhE0H1souiNBEwryNL6S4UDk_YKkC6LfoGqwDndnAjFYTzSaK-AUVAZgVjfUtOCGAQ/exec"
    
    async def get_meetings_starting_soon(self, minutes_ahead: int = 30) -> List[Dict]:
        """Get meetings starting within the specified minutes"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.api_url, 
                    params={'hours': 2}  # Get 2 hours of events
                ) as response:
                    response.raise_for_status()
                    data = await response.json()
            
            if not data.get('success'):
                logger.error(f"API returned error: {data}")
                return []
            
            meetings_soon = []
            now = datetime.now(timezone.utc)  # Use UTC timezone
            threshold = now + timedelta(minutes=minutes_ahead)
            
            logger.info(f"Current time (UTC): {now}")
            logger.info(f"Looking for meetings until: {threshold}")
            
            for event in data.get('events', []):
                try:
                    # Parse start time from API
                    start_str = event.get('startTime', '')
                    if not start_str:
                        continue
                    
                    # Handle timezone properly
                    if start_str.endswith('Z'):
                        start_time = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                    else:
                        start_time = datetime.fromisoformat(start_str)
                        if start_time.tzinfo is None:
                            start_time = start_time.replace(tzinfo=timezone.utc)
                    
                    # Calculate time difference
                    time_until = (start_time - now).total_seconds()
                    minutes_until = time_until / 60
                    
                    logger.info(f"Event '{event.get('title')}' starts at {start_time}, {minutes_until:.1f} minutes from now")
                    
                    # Check if meeting is in our target window
                    if 0 < minutes_until <= minutes_ahead:
                        event['minutes_until_start'] = int(minutes_until)
                        event['seconds_until_start'] = int(time_until)
                        meetings_soon.append(event)
                        logger.info(f"✅ Found meeting: {event.get('title')} in {minutes_until:.1f} minutes")
                    elif minutes_until <= 0:
                        logger.info(f"⏪ Past meeting: {event.get('title')} was {abs(minutes_until):.1f} minutes ago")
                    else:
                        logger.info(f"⏩ Future meeting: {event.get('title')} in {minutes_until:.1f} minutes (too far)")
                        
                except Exception as e:
                    logger.warning(f"Error processing event {event}: {e}")
                    continue
            
            logger.info(f"Found {len(meetings_soon)} meetings in next {minutes_ahead} minutes")
            return meetings_soon
            
        except Exception as e:
            logger.error(f"Error getting meetings: {e}")
            return []
    
    async def get_previous_meeting_in_series(self, meeting_title: str) -> Optional[Dict]:
        """Find previous meeting in the same series"""
        try:
            # Extract series name (first 2-3 words)
            series_name = ' '.join(meeting_title.split()[:3])
            
            logger.info(f"Searching for previous meeting in series: '{series_name}'")
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.api_url,
                    params={
                        'action': 'series',
                        'seriesName': series_name
                    }
                ) as response:
                    response.raise_for_status()
                    data = await response.json()
            
            if data.get('success') and data.get('lastMeeting'):
                last_meeting = data['lastMeeting']
                logger.info(f"✅ Found previous meeting: {last_meeting.get('title', 'Untitled')}")
                return last_meeting
            else:
                logger.info(f"No previous meeting found for series: {series_name}")
                return None
                
        except Exception as e:
            logger.error(f"Error finding previous meeting: {e}")
            return None

async def test_working_calendar():
    """Test the working calendar integration"""
    client = WorkingCalendarClient()
    
    print("🚀 Testing Working Calendar Integration")
    print("="*60)
    
    # Test 1: Check meetings in next 480 minutes (8 hours) to catch tomorrow's meetings
    print("\n1️⃣ Checking for meetings in next 8 hours...")
    upcoming = await client.get_meetings_starting_soon(480)
    
    if upcoming:
        print(f"✅ Found {len(upcoming)} upcoming meetings:")
        for meeting in upcoming:
            print(f"   📅 {meeting.get('title', 'Untitled')}")
            print(f"   ⏰ In {meeting['minutes_until_start']} minutes")
            print(f"   👥 Attendees: {len(meeting.get('attendees', []))} people")
            print(f"   🔄 Recurring: {meeting.get('isRecurring', False)}")
            print()
    else:
        print("❌ No meetings found in next 8 hours")
    
    # Test 2: Search for previous meetings in series
    print("2️⃣ Testing series search...")
    
    test_meetings = [
        "UA daily sync",
        "All Hands Chardonnay Monthly",
        "Daily Standup"  # This won't exist, should return None
    ]
    
    for meeting_title in test_meetings:
        print(f"\n🔍 Searching for previous '{meeting_title}' meeting...")
        previous = await client.get_previous_meeting_in_series(meeting_title)
        
        if previous:
            print(f"   ✅ Found: {previous.get('title', 'Untitled')}")
            print(f"   📅 Date: {previous.get('date', 'Unknown')}")
            print(f"   ⏱️  Duration: {previous.get('duration', 'Unknown')} minutes")
            print(f"   👥 Attendees: {len(previous.get('attendees', []))} people")
        else:
            print(f"   ❌ No previous meeting found")
    
    print("\n" + "="*60)
    print("✨ Test completed!")

if __name__ == "__main__":
    asyncio.run(test_working_calendar())