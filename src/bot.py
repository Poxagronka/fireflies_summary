"""Main bot module for Fireflies Summary Bot."""

import asyncio
import logging
import signal
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set
import aiohttp
from aiohttp import web

from .config import config
from .fireflies_client import FirefliesClient, Transcript
from .slack_client import SlackBot
from .calendar_integration import CalendarManager, CalendarEvent
from .meeting_analyzer import MeetingAnalyzer

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
        
        self.running = False
        self.check_task: Optional[asyncio.Task] = None
        self.processed_events: Set[str] = set()
        self.default_channel = "#general"  # Default Slack channel
        
        # Web server for health checks
        self.app = web.Application()
        self.app.router.add_get('/health', self.health_check)
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
        
        # Start the main check loop
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
            "processed_events": len(self.processed_events)
        })
    
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
            # Get events starting in the notification window
            upcoming_events = await self.calendar_manager.get_events_starting_soon(
                minutes_ahead=config.NOTIFICATION_MINUTES_BEFORE
            )
            
            logger.info(f"Found {len(upcoming_events)} upcoming events")
            
            for event in upcoming_events:
                # Skip if we've already processed this event
                event_key = f"{event.id}_{event.start_time.isoformat()}"
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
    
    async def process_event(self, event: CalendarEvent):
        """Process a calendar event and send summary if applicable."""
        logger.info(f"Processing event: {event.title} at {event.start_time}")
        
        try:
            async with self.fireflies_client as client:
                # Find previous meeting in the series
                previous_transcript = await client.find_previous_meeting_in_series(
                    meeting_title=event.title,
                    meeting_date=event.start_time
                )
                
                if previous_transcript:
                    logger.info(f"Found previous meeting: {previous_transcript.title}")
                    
                    # Send summary to Slack
                    await self.send_summary_to_slack(event, previous_transcript)
                else:
                    logger.info(f"No previous meeting found for: {event.title}")
                    
                    # Optionally send a message that this is the first meeting
                    if event.is_recurring:
                        await self.send_first_meeting_notification(event)
        
        except Exception as e:
            logger.error(f"Error processing event {event.id}: {str(e)}", exc_info=True)
    
    async def send_summary_to_slack(
        self,
        event: CalendarEvent,
        transcript: Transcript
    ):
        """Send meeting summary to Slack."""
        try:
            # Determine the channel to send to
            channel = await self.determine_slack_channel(event)
            
            if not channel:
                logger.warning(f"No Slack channel determined for event: {event.title}")
                return
            
            # Send the summary
            message_ts = await self.slack_bot.send_meeting_summary(
                channel=channel,
                meeting_title=event.title,
                meeting_time=event.start_time,
                summary=transcript.summary or "No summary available",
                action_items=transcript.action_items,
                key_topics=transcript.key_topics,
                participants=transcript.participants,
                transcript_url=transcript.meeting_url
            )
            
            if message_ts:
                logger.info(f"Summary sent to Slack channel {channel} for event: {event.title}")
            else:
                logger.error(f"Failed to send summary to Slack for event: {event.title}")
        
        except Exception as e:
            logger.error(f"Error sending summary to Slack: {str(e)}", exc_info=True)
    
    async def send_first_meeting_notification(self, event: CalendarEvent):
        """Send notification for first meeting in a series."""
        try:
            channel = await self.determine_slack_channel(event)
            
            if not channel:
                return
            
            blocks = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"📅 Upcoming Meeting: {event.title}"
                    }
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Starting in {config.NOTIFICATION_MINUTES_BEFORE} minutes* • {event.start_time.strftime('%I:%M %p')}"
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
            
            if event.description:
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Meeting Description:*\n{event.description[:500]}"
                    }
                })
            
            if event.attendees:
                attendees_text = ", ".join(event.attendees[:10])
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
                text=f"First meeting notification for {event.title}"
            )
            
            logger.info(f"First meeting notification sent for: {event.title}")
        
        except Exception as e:
            logger.error(f"Error sending first meeting notification: {str(e)}", exc_info=True)
    
    async def determine_slack_channel(self, event: CalendarEvent) -> Optional[str]:
        """Determine which Slack channel to send the summary to."""
        # For now, use the default channel
        # In the future, this could be based on:
        # - Event attendees (DM to specific users)
        # - Event title patterns (specific channels for specific meeting types)
        # - User preferences stored in a database
        
        # Try to find a channel based on the meeting title
        title_lower = event.title.lower()
        
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
        cutoff = datetime.now(timezone.utc) - timedelta(days=1)
        
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
            return datetime.now(timezone.utc)


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