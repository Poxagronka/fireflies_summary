"""Calendar integration for Google Calendar and Outlook."""

import logging
import asyncio
import json
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
import pickle
import os

# Google Calendar imports
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("Google Calendar API not available. Install google-api-python-client to enable.")

# Microsoft Graph imports
try:
    from azure.identity import ClientSecretCredential
    from msgraph.core import GraphClient
    MICROSOFT_AVAILABLE = True
except ImportError:
    MICROSOFT_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("Microsoft Graph API not available. Install msgraph-core to enable.")

from .config import config

logger = logging.getLogger(__name__)


@dataclass
class CalendarEvent:
    """Represents a calendar event."""
    id: str
    title: str
    start_time: datetime
    end_time: datetime
    attendees: List[str]
    description: Optional[str]
    location: Optional[str]
    meeting_url: Optional[str]
    is_recurring: bool
    series_id: Optional[str]


class CalendarIntegration:
    """Base class for calendar integrations."""
    
    def __init__(self):
        self.events_cache: Dict[str, CalendarEvent] = {}
        self.cache_expiry: Optional[datetime] = None
    
    async def get_upcoming_events(
        self,
        time_min: Optional[datetime] = None,
        time_max: Optional[datetime] = None,
        max_results: int = 100
    ) -> List[CalendarEvent]:
        """Get upcoming events from calendar."""
        raise NotImplementedError
    
    async def get_event_by_id(self, event_id: str) -> Optional[CalendarEvent]:
        """Get a specific event by ID."""
        raise NotImplementedError
    
    def _is_cache_valid(self) -> bool:
        """Check if the cache is still valid."""
        if not self.cache_expiry:
            return False
        return datetime.now(timezone.utc) < self.cache_expiry
    
    def _update_cache(self, events: List[CalendarEvent]):
        """Update the events cache."""
        self.events_cache.clear()
        for event in events:
            self.events_cache[event.id] = event
        self.cache_expiry = datetime.now(timezone.utc) + timedelta(minutes=5)


class GoogleCalendarIntegration(CalendarIntegration):
    """Google Calendar integration."""
    
    SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']
    
    def __init__(self):
        super().__init__()
        if not GOOGLE_AVAILABLE:
            raise ImportError("Google Calendar API not available")
        
        self.service = None
        self.credentials = None
        self._initialize_credentials()
    
    def _initialize_credentials(self):
        """Initialize Google Calendar credentials."""
        creds = None
        token_file = 'token.pickle'
        
        # Load existing token
        if os.path.exists(token_file):
            with open(token_file, 'rb') as token:
                creds = pickle.load(token)
        
        # If there are no (valid) credentials available, let the user log in
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                # Check if credentials are provided via environment
                creds_json = config.GOOGLE_CALENDAR_CREDENTIALS
                if creds_json:
                    flow = InstalledAppFlow.from_client_config(
                        json.loads(creds_json),
                        self.SCOPES
                    )
                    creds = flow.run_local_server(port=0)
                else:
                    logger.error("Google Calendar credentials not configured")
                    return
            
            # Save the credentials for the next run
            with open(token_file, 'wb') as token:
                pickle.dump(creds, token)
        
        self.credentials = creds
        self.service = build('calendar', 'v3', credentials=creds)
    
    async def get_upcoming_events(
        self,
        time_min: Optional[datetime] = None,
        time_max: Optional[datetime] = None,
        max_results: int = 100
    ) -> List[CalendarEvent]:
        """Get upcoming events from Google Calendar."""
        if not self.service:
            logger.error("Google Calendar service not initialized")
            return []
        
        # Use cache if valid
        if self._is_cache_valid() and not time_min and not time_max:
            return list(self.events_cache.values())
        
        try:
            # Set default time range
            if not time_min:
                time_min = datetime.now(timezone.utc)
            if not time_max:
                time_max = time_min + timedelta(days=7)
            
            # Call the Calendar API
            events_result = self.service.events().list(
                calendarId='primary',
                timeMin=time_min.isoformat(),
                timeMax=time_max.isoformat(),
                maxResults=max_results,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            
            # Convert to CalendarEvent objects
            calendar_events = []
            for event in events:
                calendar_event = self._parse_google_event(event)
                if calendar_event:
                    calendar_events.append(calendar_event)
            
            # Update cache
            self._update_cache(calendar_events)
            
            return calendar_events
        
        except HttpError as error:
            logger.error(f"An error occurred: {error}")
            return []
    
    async def get_event_by_id(self, event_id: str) -> Optional[CalendarEvent]:
        """Get a specific event by ID from Google Calendar."""
        if not self.service:
            return None
        
        # Check cache first
        if event_id in self.events_cache:
            return self.events_cache[event_id]
        
        try:
            event = self.service.events().get(
                calendarId='primary',
                eventId=event_id
            ).execute()
            
            return self._parse_google_event(event)
        
        except HttpError as error:
            logger.error(f"Failed to get event {event_id}: {error}")
            return None
    
    def _parse_google_event(self, event: Dict[str, Any]) -> Optional[CalendarEvent]:
        """Parse Google Calendar event to CalendarEvent object."""
        try:
            # Parse start and end times
            start = event['start'].get('dateTime', event['start'].get('date'))
            end = event['end'].get('dateTime', event['end'].get('date'))
            
            if isinstance(start, str):
                start_time = datetime.fromisoformat(start.replace('Z', '+00:00'))
            else:
                start_time = datetime.now(timezone.utc)
            
            if isinstance(end, str):
                end_time = datetime.fromisoformat(end.replace('Z', '+00:00'))
            else:
                end_time = start_time + timedelta(hours=1)
            
            # Extract attendees
            attendees = []
            for attendee in event.get('attendees', []):
                email = attendee.get('email', '')
                name = attendee.get('displayName', email)
                attendees.append(name)
            
            # Extract meeting URL
            meeting_url = None
            if 'conferenceData' in event:
                entry_points = event['conferenceData'].get('entryPoints', [])
                for entry in entry_points:
                    if entry.get('entryPointType') == 'video':
                        meeting_url = entry.get('uri')
                        break
            
            # Check if recurring
            is_recurring = 'recurringEventId' in event
            series_id = event.get('recurringEventId')
            
            return CalendarEvent(
                id=event['id'],
                title=event.get('summary', 'Untitled Event'),
                start_time=start_time,
                end_time=end_time,
                attendees=attendees,
                description=event.get('description'),
                location=event.get('location'),
                meeting_url=meeting_url,
                is_recurring=is_recurring,
                series_id=series_id
            )
        
        except Exception as e:
            logger.error(f"Failed to parse Google event: {str(e)}")
            return None


class OutlookCalendarIntegration(CalendarIntegration):
    """Microsoft Outlook calendar integration."""
    
    def __init__(self, tenant_id: str, client_id: str, client_secret: str):
        super().__init__()
        if not MICROSOFT_AVAILABLE:
            raise ImportError("Microsoft Graph API not available")
        
        self.credential = ClientSecretCredential(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret
        )
        self.client = GraphClient(
            credential=self.credential,
            scopes=['https://graph.microsoft.com/.default']
        )
    
    async def get_upcoming_events(
        self,
        time_min: Optional[datetime] = None,
        time_max: Optional[datetime] = None,
        max_results: int = 100
    ) -> List[CalendarEvent]:
        """Get upcoming events from Outlook Calendar."""
        # Use cache if valid
        if self._is_cache_valid() and not time_min and not time_max:
            return list(self.events_cache.values())
        
        try:
            # Set default time range
            if not time_min:
                time_min = datetime.now(timezone.utc)
            if not time_max:
                time_max = time_min + timedelta(days=7)
            
            # Build filter query
            filter_query = f"start/dateTime ge '{time_min.isoformat()}' and start/dateTime le '{time_max.isoformat()}'"
            
            # Make API request
            response = await self.client.get(
                f'/me/events',
                params={
                    '$filter': filter_query,
                    '$top': max_results,
                    '$orderby': 'start/dateTime'
                }
            )
            
            events = response.json().get('value', [])
            
            # Convert to CalendarEvent objects
            calendar_events = []
            for event in events:
                calendar_event = self._parse_outlook_event(event)
                if calendar_event:
                    calendar_events.append(calendar_event)
            
            # Update cache
            self._update_cache(calendar_events)
            
            return calendar_events
        
        except Exception as e:
            logger.error(f"Failed to get Outlook events: {str(e)}")
            return []
    
    async def get_event_by_id(self, event_id: str) -> Optional[CalendarEvent]:
        """Get a specific event by ID from Outlook Calendar."""
        # Check cache first
        if event_id in self.events_cache:
            return self.events_cache[event_id]
        
        try:
            response = await self.client.get(f'/me/events/{event_id}')
            event = response.json()
            
            return self._parse_outlook_event(event)
        
        except Exception as e:
            logger.error(f"Failed to get Outlook event {event_id}: {str(e)}")
            return None
    
    def _parse_outlook_event(self, event: Dict[str, Any]) -> Optional[CalendarEvent]:
        """Parse Outlook event to CalendarEvent object."""
        try:
            # Parse start and end times
            start_dt = event['start'].get('dateTime', '')
            end_dt = event['end'].get('dateTime', '')
            
            start_time = datetime.fromisoformat(start_dt.replace('Z', '+00:00'))
            end_time = datetime.fromisoformat(end_dt.replace('Z', '+00:00'))
            
            # Extract attendees
            attendees = []
            for attendee in event.get('attendees', []):
                name = attendee.get('emailAddress', {}).get('name', '')
                email = attendee.get('emailAddress', {}).get('address', '')
                attendees.append(name or email)
            
            # Extract meeting URL
            meeting_url = None
            if event.get('isOnlineMeeting'):
                online_meeting = event.get('onlineMeeting', {})
                meeting_url = online_meeting.get('joinUrl')
            
            # Check if recurring
            is_recurring = event.get('type') == 'occurrence'
            series_id = event.get('seriesMasterId')
            
            return CalendarEvent(
                id=event['id'],
                title=event.get('subject', 'Untitled Event'),
                start_time=start_time,
                end_time=end_time,
                attendees=attendees,
                description=event.get('bodyPreview'),
                location=event.get('location', {}).get('displayName'),
                meeting_url=meeting_url,
                is_recurring=is_recurring,
                series_id=series_id
            )
        
        except Exception as e:
            logger.error(f"Failed to parse Outlook event: {str(e)}")
            return None


class CalendarManager:
    """Manager for handling multiple calendar integrations."""
    
    def __init__(self):
        self.integrations: List[CalendarIntegration] = []
        self._initialize_integrations()
    
    def _initialize_integrations(self):
        """Initialize available calendar integrations."""
        # Try to initialize Google Calendar
        if GOOGLE_AVAILABLE and config.GOOGLE_CALENDAR_CREDENTIALS:
            try:
                google_cal = GoogleCalendarIntegration()
                self.integrations.append(google_cal)
                logger.info("Google Calendar integration initialized")
            except Exception as e:
                logger.error(f"Failed to initialize Google Calendar: {str(e)}")
        
        # Add Outlook integration if configured
        # (would need additional config for tenant_id, client_id, client_secret)
    
    async def get_all_upcoming_events(
        self,
        time_min: Optional[datetime] = None,
        time_max: Optional[datetime] = None
    ) -> List[CalendarEvent]:
        """Get upcoming events from all configured calendars."""
        all_events = []
        
        for integration in self.integrations:
            try:
                events = await integration.get_upcoming_events(time_min, time_max)
                all_events.extend(events)
            except Exception as e:
                logger.error(f"Failed to get events from {integration.__class__.__name__}: {str(e)}")
        
        # Sort by start time
        all_events.sort(key=lambda x: x.start_time)
        
        return all_events
    
    async def get_events_starting_soon(
        self,
        minutes_ahead: int = 30
    ) -> List[CalendarEvent]:
        """Get events starting within the specified minutes."""
        now = datetime.now(timezone.utc)
        time_min = now + timedelta(minutes=minutes_ahead - 5)
        time_max = now + timedelta(minutes=minutes_ahead + 5)
        
        return await self.get_all_upcoming_events(time_min, time_max)