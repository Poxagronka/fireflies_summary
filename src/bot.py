"""Main bot module for Fireflies Summary Bot."""

import asyncio
import logging
import signal
import sys
from datetime import datetime, timedelta, timezone
import pytz
from typing import Dict, List, Optional, Set
import aiohttp
from aiohttp import web

from .config import config
from .fireflies_client import FirefliesClient, Transcript
from .slack_client import SlackBot
from .calendar_integration import CalendarManager, CalendarEvent
from .meeting_analyzer import MeetingAnalyzer
from .google_calendar_integration import GoogleCalendarClient

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class FirefliesSummaryBot:
    """Main bot class that coordinates all components."""
    
    def __init__(self):
        self.fireflies_client = FirefliesClient()
        self.slack_bot = SlackBot()
        self.calendar_manager = CalendarManager()
        self.meeting_analyzer = MeetingAnalyzer()
        
        # Add Google Apps Script calendar integration
        try:
            self.google_calendar_client = GoogleCalendarClient()
            logger.info("✅ Google Apps Script Calendar integration initialized")
        except Exception as e:
            logger.warning(f"Google Apps Script Calendar not available: {e}")
            self.google_calendar_client = None
        
        self.running = False
        self.check_task: Optional[asyncio.Task] = None
        self.processed_events: Set[str] = set()
        self.default_channel = "#general"  # Default Slack channel
        
        # Web server for health checks
        self.app = web.Application()
        self.app.router.add_get('/health', self.health_check)
        self.app.router.add_get('/force-check', self.force_check_meetings)
        self.app.router.add_get('/test-meeting/{meeting_name}', self.test_meeting_summary)
        self.app.router.add_get('/test-fireflies-api', self.test_fireflies_api)
        self.app.router.add_get('/debug-search/{keyword}', self.debug_search)
        self.app.router.add_get('/schedule-preview', self.schedule_preview)
        self.app.router.add_get('/test-slack-message', self.test_slack_message)
        self.runner: Optional[web.AppRunner] = None
    
    async def start(self):
        """Start the bot and all its components."""
        logger.info("Starting Fireflies Summary Bot...")
        
        # Validate configuration
        try:
            config.validate()
        except ValueError as e:
            logger.error(f"Configuration error: {str(e)}")
            sys.exit(1)
        
        self.running = True
        
        # Start web server for health checks
        await self.start_web_server()
        
        # Start Slack bot
        await self.slack_bot.start()
        
        # Start the main check loop (now with 6-hour interval)
        self.check_task = asyncio.create_task(self.check_loop())
        
        logger.info("Bot started successfully!")
        
        # Set up signal handlers
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda s, f: asyncio.create_task(self.shutdown()))
        
        # Keep running
        try:
            await self.check_task
        except asyncio.CancelledError:
            pass
    
    async def shutdown(self):
        """Gracefully shutdown the bot."""
        logger.info("Shutting down bot...")
        self.running = False
        
        if self.check_task:
            self.check_task.cancel()
        
        if self.runner:
            await self.runner.cleanup()
        
        logger.info("Bot shutdown complete")
    
    async def get_upcoming_meetings_apps_script(self):
        """Get meetings from Google Apps Script calendar."""
        if not self.google_calendar_client:
            return []
        
        try:
            events = await self.google_calendar_client.get_upcoming_events(minutes_ahead=7*24*60)  # 7 days
            return events
        except Exception as e:
            logger.error(f"Error getting Apps Script meetings: {e}")
            return []
    
    
    async def start_web_server(self):
        """Start the web server for health checks."""
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, config.HOST, config.PORT)
        await site.start()
        logger.info(f"Web server started on {config.HOST}:{config.PORT}")
    
    async def health_check(self, request):
        """Health check endpoint."""
        return web.json_response({
            "status": "healthy",
            "running": self.running,
            "processed_events": len(self.processed_events),
            "google_calendar_ok": self.google_calendar_client.connection_ok if self.google_calendar_client else False,
            "check_interval_minutes": config.CHECK_INTERVAL_MINUTES
        })
    
    
    async def force_check_meetings(self, request):
        """Force check for meetings (for testing)."""
        try:
            logger.info("Force checking meetings triggered via HTTP")
            await self.check_upcoming_meetings()
            
            return web.json_response({
                "status": "success",
                "message": "Meeting check completed",
                "processed_events": len(self.processed_events)
            })
        except Exception as e:
            logger.error(f"Force check error: {e}")
            return web.json_response({
                "status": "error", 
                "message": str(e)
            }, status=500)
    
    async def schedule_preview(self, request):
        """Show schedule preview and summary send plan."""
        try:
            warsaw_tz = pytz.timezone('Europe/Warsaw')
            current_time = datetime.now(warsaw_tz)
            
            logger.info("Getting schedule preview...")
            
            # Get upcoming meetings from both sources
            upcoming_meetings = []
            
            # Get from Google Apps Script
            if self.google_calendar_client and self.google_calendar_client.connection_ok:
                try:
                    apps_script_events = await self.google_calendar_client.get_upcoming_events(minutes_ahead=7*24*60)  # 7 days
                    upcoming_meetings.extend(apps_script_events)
                    logger.info(f"Found {len(apps_script_events)} events from Apps Script")
                except Exception as e:
                    logger.error(f"Apps Script error: {e}")
            
            # Process meetings and create summary send plan
            summary_plan = []
            for meeting in upcoming_meetings:
                try:
                    # Parse meeting start time
                    start_time_str = meeting.get('startTime') or meeting.get('start_time')
                    if not start_time_str:
                        continue
                    
                    if isinstance(start_time_str, datetime):
                        meeting_start = start_time_str
                    else:
                        meeting_start = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                    
                    # Convert to Warsaw time
                    if meeting_start.tzinfo is None:
                        meeting_start = warsaw_tz.localize(meeting_start)
                    else:
                        meeting_start = meeting_start.astimezone(warsaw_tz)
                    
                    # Skip past meetings
                    if meeting_start <= current_time:
                        continue
                    
                    # Calculate when to send summary (30 minutes before)
                    summary_send_time = meeting_start - timedelta(minutes=config.NOTIFICATION_MINUTES_BEFORE)
                    
                    # Skip if summary time is in the past
                    if summary_send_time <= current_time:
                        continue
                    
                    # Calculate time until summary and meeting
                    time_until_summary = summary_send_time - current_time
                    time_until_meeting = meeting_start - current_time
                    
                    meeting_info = {
                        "title": meeting.get('title', 'Untitled Meeting'),
                        "meeting_start": meeting_start.isoformat(),
                        "summary_send_time": summary_send_time.isoformat(),
                        "hours_until_summary": round(time_until_summary.total_seconds() / 3600, 1),
                        "hours_until_meeting": round(time_until_meeting.total_seconds() / 3600, 1),
                        "meeting_url": meeting.get('meetingUrl') or meeting.get('meeting_url', ''),
                        "source": "Apps Script"
                    }
                    
                    summary_plan.append(meeting_info)
                    
                except Exception as e:
                    logger.warning(f"Failed to process meeting {meeting.get('title', 'unknown')}: {e}")
            
            # Sort by summary send time
            summary_plan.sort(key=lambda x: x['summary_send_time'])
            
            # Calculate next bot check times (every 6 hours)
            next_checks = []
            for i in range(4):  # Next 4 checks (24 hours)
                if i == 0:
                    next_check = current_time
                    status = "Current check"
                else:
                    next_check = current_time + timedelta(hours=6*i)
                    status = "Upcoming check"
                    
                next_checks.append({
                    "check_number": i + 1,
                    "check_time": next_check.isoformat(),
                    "hours_from_now": round((next_check - current_time).total_seconds() / 3600, 1),
                    "status": status
                })
            
            response = {
                "current_time": current_time.isoformat(),
                "timezone": "Europe/Warsaw",
                "check_interval_hours": config.CHECK_INTERVAL_MINUTES / 60,
                "notification_minutes_before": config.NOTIFICATION_MINUTES_BEFORE,
                "next_bot_checks": next_checks,
                "upcoming_meetings": len(summary_plan),
                "summary_send_plan": summary_plan[:10]  # Show next 10 meetings
            }
            
            return web.json_response(response)
            
        except Exception as e:
            logger.error(f"Error in schedule preview: {e}")
            return web.json_response({
                "error": str(e),
                "current_time": datetime.now(pytz.timezone('Europe/Warsaw')).isoformat()
            }, status=500)
    
    async def test_slack_message(self, request):
        """Send a test message to Slack to verify bot can send messages."""
        try:
            warsaw_tz = pytz.timezone('Europe/Warsaw')
            current_time = datetime.now(warsaw_tz)
            
            logger.info("Sending test message to Slack...")
            
            # Get channel from request parameter or use default
            channel_name = request.query.get('channel', 'general')
            if not channel_name.startswith('#'):
                channel_name = f"#{channel_name}"
            channel_id = channel_name
            
            logger.info(f"Sending test message to channel: {channel_id}")
            
            # Create test message with system info
            test_message = {
                "text": "🤖 Тестовое сообщение от Fireflies Summary Bot",
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": "🤖 Тест Fireflies Summary Bot"
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Время отправки:* {current_time.strftime('%d.%m.%Y %H:%M')} (Warsaw)\n*Статус:* ✅ Бот работает корректно\n*Интервал проверки:* {config.CHECK_INTERVAL_MINUTES // 60} часов\n*Отправка саммари:* за {config.NOTIFICATION_MINUTES_BEFORE} минут до встречи"
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "🔄 *График работы:*\n• Проверка календаря каждые 6 часов\n• Поиск транскриптов в Fireflies\n• Автоматическая отправка саммари"
                        }
                    },
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": "🔗 Система энергоэффективна: 98.6% экономии ресурсов"
                            }
                        ]
                    }
                ]
            }
            
            # Send message via Slack client using blocks
            message_ts = await self.slack_bot.send_blocks(
                channel=channel_id,
                blocks=test_message["blocks"],
                text=test_message["text"]
            )
            success = message_ts is not None
            
            if success:
                return web.json_response({
                    "status": "success",
                    "message": "Test message sent to Slack successfully",
                    "channel": channel_id,
                    "sent_at": current_time.isoformat(),
                    "bot_status": "operational"
                })
            else:
                return web.json_response({
                    "status": "error", 
                    "message": "Failed to send test message to Slack",
                    "channel": channel_id
                }, status=500)
                
        except Exception as e:
            logger.error(f"Error sending test Slack message: {e}")
            return web.json_response({
                "status": "error",
                "message": f"Error sending test message: {str(e)}",
                "timestamp": datetime.now(pytz.timezone('Europe/Warsaw')).isoformat()
            }, status=500)
    
    async def test_meeting_summary(self, request):
        """Test meeting summary search (for testing)."""
        meeting_name = request.match_info.get('meeting_name', '')
        
        try:
            logger.info(f"Testing meeting summary for: {meeting_name}")
            
            result = {
                "meeting_name": meeting_name,
                "calendar_previous": None,
                "fireflies_transcript": None,
                "would_send_summary": False
            }
            
            # Check Google Calendar for previous meeting
            if self.google_calendar_client:
                try:
                    previous_meeting = await self.google_calendar_client.get_previous_meeting_in_series(meeting_name)
                    if previous_meeting:
                        result["calendar_previous"] = {
                            "title": previous_meeting.get("title"),
                            "date": previous_meeting.get("date"),
                            "attendees_count": len(previous_meeting.get("attendees", []))
                        }
                except Exception as e:
                    logger.error(f"Calendar search error: {e}")
            
            # Check Fireflies for transcript
            try:
                async with self.fireflies_client as client:
                    # Use Warsaw timezone for meeting search
                    warsaw_tz = pytz.timezone('Europe/Warsaw')
                    current_time = datetime.now(warsaw_tz)
                    transcript = await client.find_previous_meeting_in_series(
                        meeting_name,
                        current_time
                    )
                    if transcript:
                        result["fireflies_transcript"] = {
                            "title": transcript.title,
                            "date": transcript.date.isoformat(),
                            "summary": transcript.summary[:200] if transcript.summary else None,
                            "action_items_count": len(transcript.action_items),
                            "participants_count": len(transcript.participants)
                        }
                        result["would_send_summary"] = True
            except Exception as e:
                logger.error(f"Fireflies search error: {e}")
            
            return web.json_response(result)
            
        except Exception as e:
            logger.error(f"Test meeting error: {e}")
            return web.json_response({
                "status": "error",
                "message": str(e)
            }, status=500)
    
    async def test_fireflies_api(self, request):
        """Test basic Fireflies API functionality."""
        try:
            logger.info("Testing Fireflies API functionality")
            
            result = {
                "status": "success",
                "tests": {}
            }
            
            # Test 1: Get all transcripts
            try:
                async with self.fireflies_client as client:
                    all_transcripts = await client.get_transcripts(limit=10, include_shared=True)
                    result["tests"]["get_transcripts"] = {
                        "success": True,
                        "count": len(all_transcripts),
                        "transcripts": [
                            {
                                "title": t.title,
                                "date": t.date.isoformat(),
                                "participants": len(t.participants),
                                "has_summary": bool(t.summary)
                            } for t in all_transcripts[:5]
                        ]
                    }
            except Exception as e:
                result["tests"]["get_transcripts"] = {
                    "success": False,
                    "error": str(e)
                }
            
            # Test 2: Search by keywords
            keywords = ["UA", "daily", "sync", "automation", "weekly"]
            result["tests"]["keyword_search"] = {}
            
            for keyword in keywords:
                try:
                    async with self.fireflies_client as client:
                        search_results = await client.search_transcripts(
                            title_pattern=keyword,
                            limit=3,
                            include_shared=True
                        )
                        result["tests"]["keyword_search"][keyword] = {
                            "success": True,
                            "count": len(search_results),
                            "matches": [t.title for t in search_results]
                        }
                except Exception as e:
                    result["tests"]["keyword_search"][keyword] = {
                        "success": False,
                        "error": str(e)
                    }
            
            # Test 3: Compare my vs all meetings
            try:
                async with self.fireflies_client as client:
                    my_meetings = await client._get_transcripts_with_filter(20, mine=True)
                    all_meetings = await client._get_transcripts_with_filter(20, mine=None)
                    
                    my_ids = {t.id for t in my_meetings}
                    shared_meetings = [t for t in all_meetings if t.id not in my_ids]
                    
                    result["tests"]["meeting_categories"] = {
                        "success": True,
                        "my_meetings": len(my_meetings),
                        "all_meetings": len(all_meetings), 
                        "shared_meetings": len(shared_meetings),
                        "shared_titles": [t.title for t in shared_meetings[:5]]
                    }
            except Exception as e:
                result["tests"]["meeting_categories"] = {
                    "success": False,
                    "error": str(e)
                }
            
            return web.json_response(result)
            
        except Exception as e:
            logger.error(f"Fireflies API test error: {e}")
            return web.json_response({
                "status": "error",
                "message": str(e)
            }, status=500)
    
    async def debug_search(self, request):
        """Debug search functionality."""
        keyword = request.match_info.get('keyword', '')
        
        try:
            logger.info(f"Debug search for keyword: {keyword}")
            
            result = {
                "keyword": keyword,
                "searches": {}
            }
            
            async with self.fireflies_client as client:
                # Test 1: Direct search by keyword
                try:
                    search_results = await client.search_transcripts(
                        title_pattern=keyword,
                        limit=10,
                        include_shared=True
                    )
                    result["searches"]["keyword_search"] = {
                        "success": True,
                        "count": len(search_results),
                        "results": [
                            {
                                "title": t.title,
                                "date": t.date.isoformat(),
                                "participants": len(t.participants),
                                "has_summary": bool(t.summary)
                            } for t in search_results
                        ]
                    }
                except Exception as e:
                    result["searches"]["keyword_search"] = {
                        "success": False,
                        "error": str(e)
                    }
                
                # Test 2: Get all and filter manually  
                try:
                    all_transcripts = await client.get_transcripts(limit=50, include_shared=True)
                    matched = [
                        t for t in all_transcripts 
                        if keyword.lower() in t.title.lower()
                    ]
                    result["searches"]["manual_filter"] = {
                        "success": True,
                        "total_transcripts": len(all_transcripts),
                        "matched_count": len(matched),
                        "matches": [
                            {
                                "title": t.title,
                                "date": t.date.isoformat(),
                                "participants": len(t.participants)
                            } for t in matched[:10]
                        ]
                    }
                except Exception as e:
                    result["searches"]["manual_filter"] = {
                        "success": False,
                        "error": str(e)
                    }
            
            return web.json_response(result)
            
        except Exception as e:
            logger.error(f"Debug search error: {e}")
            return web.json_response({
                "status": "error",
                "message": str(e)
            }, status=500)
    
    async def check_loop(self):
        """Main loop that checks for upcoming meetings."""
        while self.running:
            try:
                await self.check_upcoming_meetings()
                
                # Wait for the check interval
                await asyncio.sleep(config.CHECK_INTERVAL_MINUTES * 60)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in check loop: {str(e)}", exc_info=True)
                await asyncio.sleep(60)  # Wait a minute before retrying
    
    async def check_upcoming_meetings(self):
        """Check for upcoming meetings and send summaries."""
        logger.info("Checking for upcoming meetings...")
        
        try:
            # Get events from Google Apps Script calendar (preferred)
            upcoming_events = []
            if self.google_calendar_client and self.google_calendar_client.connection_ok:
                try:
                    upcoming_events = await self.google_calendar_client.get_meetings_starting_soon(
                        minutes_ahead=config.NOTIFICATION_MINUTES_BEFORE
                    )
                    logger.info(f"Found {len(upcoming_events)} upcoming events from Google Apps Script")
                except Exception as e:
                    logger.error(f"Google Apps Script Calendar error: {e}")
                    upcoming_events = []
            
            # Fallback to standard calendar if no events from Apps Script
            if not upcoming_events:
                try:
                    standard_events = await self.calendar_manager.get_events_starting_soon(
                        minutes_ahead=config.NOTIFICATION_MINUTES_BEFORE
                    )
                    # Convert to expected format
                    upcoming_events = []
                    for event in standard_events:
                        upcoming_events.append({
                            'id': event.id,
                            'title': event.title,
                            'startTime': event.start_time.isoformat(),
                            'endTime': event.end_time.isoformat(),
                            'attendees': [{'email': a} for a in event.attendees],
                            'isRecurring': event.is_recurring,
                            'seriesId': event.series_id,
                            'meetingUrl': event.meeting_url
                        })
                    logger.info(f"Found {len(upcoming_events)} upcoming events from standard calendar")
                except Exception as e:
                    logger.error(f"Standard calendar error: {e}")
                    upcoming_events = []
            
            for event in upcoming_events:
                # Skip if we've already processed this event
                event_key = f"{event.get('id', 'unknown')}_{event.get('startTime', '')}"
                if event_key in self.processed_events:
                    continue
                
                # Process the event
                await self.process_event(event)
                
                # Mark as processed
                self.processed_events.add(event_key)
                
                # Clean up old processed events (older than 1 day)
                self._cleanup_processed_events()
        
        except Exception as e:
            logger.error(f"Error checking upcoming meetings: {str(e)}", exc_info=True)
    
    async def process_event(self, event: Dict):
        """Process a calendar event and send summary if applicable."""
        logger.info(f"Processing event: {event.get('title', 'Untitled')} at {event.get('startTime', 'Unknown time')}")
        
        try:
            # Try to find previous meeting using Google Apps Script first
            previous_meeting_data = None
            if self.google_calendar_client:
                try:
                    previous_meeting_data = await self.google_calendar_client.get_previous_meeting_in_series(
                        event.get('title', '')
                    )
                except Exception as e:
                    logger.error(f"Error getting previous meeting from Apps Script: {e}")
            
            # Then try to find transcript in Fireflies
            async with self.fireflies_client as client:
                # Find previous meeting in the series
                previous_transcript = await client.find_previous_meeting_in_series(
                    meeting_title=event.get('title', ''),
                    meeting_date=datetime.fromisoformat(event.get('startTime', '').replace('Z', '+00:00'))
                )
                
                if previous_transcript:
                    logger.info(f"Found previous meeting: {previous_transcript.title}")
                    
                    # Send summary to Slack
                    await self.send_summary_to_slack(event, previous_transcript, previous_meeting_data)
                else:
                    logger.info(f"No previous meeting found for: {event.get('title', 'Untitled')}")
                    
                    # Optionally send a message that this is the first meeting
                    if event.get('isRecurring', False):
                        await self.send_first_meeting_notification(event)
        
        except Exception as e:
            logger.error(f"Error processing event {event.get('id', 'unknown')}: {str(e)}", exc_info=True)
    
    async def send_summary_to_slack(
        self,
        event: Dict,
        transcript: Transcript,
        previous_meeting_data: Optional[Dict] = None
    ):
        """Send meeting summary to Slack."""
        try:
            # Determine the channel to send to
            channel = await self.determine_slack_channel(event)
            
            if not channel:
                logger.warning(f"No Slack channel determined for event: {event.get('title', 'Untitled')}")
                return
            
            # Parse meeting time
            try:
                meeting_time = datetime.fromisoformat(event.get('startTime', '').replace('Z', '+00:00'))
            except:
                # Use Warsaw timezone for consistency
                warsaw_tz = pytz.timezone('Europe/Warsaw')
                meeting_time = datetime.now(warsaw_tz)
            
            # Send the summary
            message_ts = await self.slack_bot.send_meeting_summary(
                channel=channel,
                meeting_title=event.get('title', 'Untitled Meeting'),
                meeting_time=meeting_time,
                summary=transcript.summary or "No summary available",
                action_items=transcript.action_items,
                key_topics=transcript.key_topics,
                participants=transcript.participants,
                transcript_url=transcript.meeting_url or event.get('meetingUrl')
            )
            
            if message_ts:
                logger.info(f"Summary sent to Slack channel {channel} for event: {event.get('title', 'Untitled')}")
            else:
                logger.error(f"Failed to send summary to Slack for event: {event.get('title', 'Untitled')}")
        
        except Exception as e:
            logger.error(f"Error sending summary to Slack: {str(e)}", exc_info=True)
    
    async def send_first_meeting_notification(self, event: Dict):
        """Send notification for first meeting in a series."""
        try:
            channel = await self.determine_slack_channel(event)
            
            if not channel:
                return
            
            # Parse meeting time
            try:
                meeting_time = datetime.fromisoformat(event.get('startTime', '').replace('Z', '+00:00'))
                time_str = meeting_time.strftime('%I:%M %p')
            except:
                time_str = 'Unknown time'
            
            blocks = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"📅 Upcoming Meeting: {event.get('title', 'Untitled')}"
                    }
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Starting in {config.NOTIFICATION_MINUTES_BEFORE} minutes* • {time_str}"
                        }
                    ]
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "_This appears to be the first meeting in this series. No previous summary available._"
                    }
                }
            ]
            
            if event.get('description'):
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Meeting Description:*\n{event.get('description', '')[:500]}"
                    }
                })
            
            attendees = event.get('attendees', [])
            if attendees:
                # Handle both string and dict formats for attendees
                attendee_names = []
                for attendee in attendees:
                    if isinstance(attendee, dict):
                        attendee_names.append(attendee.get('email', attendee.get('name', 'Unknown')))
                    else:
                        attendee_names.append(str(attendee))
                
                if attendee_names:
                    attendees_text = ", ".join(attendee_names[:10])
                    blocks.append({
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": f"*Attendees:* {attendees_text}"
                            }
                        ]
                    })
            
            await self.slack_bot.send_blocks(
                channel=channel,
                blocks=blocks,
                text=f"First meeting notification for {event.get('title', 'Untitled')}"
            )
            
            logger.info(f"First meeting notification sent for: {event.get('title', 'Untitled')}")
        
        except Exception as e:
            logger.error(f"Error sending first meeting notification: {str(e)}", exc_info=True)
    
    async def determine_slack_channel(self, event: Dict) -> Optional[str]:
        """Determine which Slack channel to send the summary to."""
        # For now, use the default channel
        # In the future, this could be based on:
        # - Event attendees (DM to specific users)
        # - Event title patterns (specific channels for specific meeting types)
        # - User preferences stored in a database
        
        # Try to find a channel based on the meeting title
        title_lower = event.get('title', '').lower()
        
        if "engineering" in title_lower or "dev" in title_lower:
            channel = "#engineering"
        elif "product" in title_lower:
            channel = "#product"
        elif "design" in title_lower:
            channel = "#design"
        elif "standup" in title_lower or "daily" in title_lower:
            channel = "#standups"
        else:
            channel = self.default_channel
        
        # Verify the channel exists
        channel_id = await self.slack_bot.get_channel_id(channel.lstrip("#"))
        if channel_id:
            return channel_id
        
        # Fall back to default channel
        return await self.slack_bot.get_channel_id(self.default_channel.lstrip("#"))
    
    def _cleanup_processed_events(self):
        """Remove old processed events from the set."""
        # Use Warsaw timezone for consistency
        warsaw_tz = pytz.timezone('Europe/Warsaw')
        cutoff = datetime.now(warsaw_tz) - timedelta(days=1)
        
        # Filter out old events
        self.processed_events = {
            event_key for event_key in self.processed_events
            if self._parse_event_key_time(event_key) > cutoff
        }
    
    def _parse_event_key_time(self, event_key: str) -> datetime:
        """Parse the timestamp from an event key."""
        try:
            # Event key format: "eventId_timestamp"
            _, timestamp = event_key.rsplit("_", 1)
            return datetime.fromisoformat(timestamp)
        except:
            # Use Warsaw timezone as default
            warsaw_tz = pytz.timezone('Europe/Warsaw')
            return datetime.now(warsaw_tz)


async def main():
    """Main entry point."""
    bot = FirefliesSummaryBot()
    
    try:
        await bot.start()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
    finally:
        await bot.shutdown()


if __name__ == "__main__":
    asyncio.run(main())