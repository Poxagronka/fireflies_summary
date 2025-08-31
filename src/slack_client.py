"""Slack client for sending messages and handling events."""

import logging
import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import json

from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.errors import SlackApiError
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from .config import config

logger = logging.getLogger(__name__)


class SlackBot:
    """Slack bot for sending meeting summaries."""
    
    def __init__(self):
        self.client = AsyncWebClient(token=config.SLACK_BOT_TOKEN)
        self.app = AsyncApp(
            token=config.SLACK_BOT_TOKEN,
            signing_secret=config.SLACK_SIGNING_SECRET
        )
        self.setup_handlers()
        self.default_channel = None
        self.scheduled_messages: Dict[str, Any] = {}
    
    def setup_handlers(self):
        """Set up Slack event handlers."""
        
        @self.app.event("app_mention")
        async def handle_app_mention(event, say):
            """Handle bot mentions."""
            await say(f"Hi <@{event['user']}>! I'm the Fireflies Summary Bot. I'll send you meeting summaries before your meetings.")
        
        @self.app.command("/fireflies-summary")
        async def handle_command(ack, body, respond):
            """Handle slash commands."""
            await ack()
            
            command_text = body.get("text", "").strip()
            user_id = body["user_id"]
            
            if command_text == "help":
                await respond(self._get_help_message())
            elif command_text == "status":
                await respond(self._get_status_message())
            elif command_text.startswith("subscribe"):
                meeting_series = command_text.replace("subscribe", "").strip()
                await respond(f"Subscribed to meeting series: {meeting_series}")
            elif command_text.startswith("unsubscribe"):
                meeting_series = command_text.replace("unsubscribe", "").strip()
                await respond(f"Unsubscribed from meeting series: {meeting_series}")
            else:
                await respond("Unknown command. Use `/fireflies-summary help` for available commands.")
    
    async def send_message(
        self,
        channel: str,
        text: str,
        thread_ts: Optional[str] = None
    ) -> Optional[str]:
        """Send a simple text message to Slack."""
        try:
            response = await self.client.chat_postMessage(
                channel=channel,
                text=text,
                thread_ts=thread_ts
            )
            return response["ts"]
        except SlackApiError as e:
            logger.error(f"Failed to send message: {e.response['error']}")
            return None
    
    async def send_blocks(
        self,
        channel: str,
        blocks: List[Dict],
        text: str = "Meeting Summary",
        thread_ts: Optional[str] = None
    ) -> Optional[str]:
        """Send formatted blocks to Slack."""
        try:
            response = await self.client.chat_postMessage(
                channel=channel,
                blocks=blocks,
                text=text,
                thread_ts=thread_ts
            )
            return response["ts"]
        except SlackApiError as e:
            logger.error(f"Failed to send blocks: {e.response['error']}")
            return None
    
    async def send_meeting_summary(
        self,
        channel: str,
        meeting_title: str,
        meeting_time: datetime,
        summary: str,
        action_items: List[str],
        key_topics: List[str],
        participants: List[str],
        transcript_url: Optional[str] = None
    ) -> Optional[str]:
        """Send a formatted meeting summary to Slack."""
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"📅 Upcoming Meeting: {meeting_title}"
                }
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Starting in 30 minutes* • {meeting_time.strftime('%I:%M %p')}"
                    }
                ]
            },
            {
                "type": "divider"
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*📝 Summary from Previous Meeting*"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": summary if summary else "_No summary available from previous meeting_"
                }
            }
        ]
        
        # Add action items if available
        if action_items:
            action_items_text = "\n".join([f"• {item}" for item in action_items[:5]])
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*✅ Action Items from Last Meeting:*\n{action_items_text}"
                }
            })
        
        # Add key topics if available
        if key_topics:
            topics_text = " • ".join([f"`{topic}`" for topic in key_topics[:5]])
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*🏷️ Key Topics:* {topics_text}"
                }
            })
        
        # Add participants if available
        if participants:
            participants_text = ", ".join(participants[:10])
            blocks.append({
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Participants:* {participants_text}"
                    }
                ]
            })
        
        # Add link to full transcript if available
        if transcript_url:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"<{transcript_url}|View Full Transcript in Fireflies>"
                }
            })
        
        blocks.append({"type": "divider"})
        
        return await self.send_blocks(
            channel=channel,
            blocks=blocks,
            text=f"Meeting Summary for {meeting_title}"
        )
    
    async def schedule_message(
        self,
        channel: str,
        scheduled_time: datetime,
        text: str
    ) -> Optional[str]:
        """Schedule a message to be sent at a specific time."""
        try:
            timestamp = int(scheduled_time.timestamp())
            response = await self.client.chat_scheduleMessage(
                channel=channel,
                text=text,
                post_at=timestamp
            )
            
            scheduled_id = response["scheduled_message_id"]
            self.scheduled_messages[scheduled_id] = {
                "channel": channel,
                "time": scheduled_time,
                "text": text
            }
            
            logger.info(f"Scheduled message {scheduled_id} for {scheduled_time}")
            return scheduled_id
        except SlackApiError as e:
            logger.error(f"Failed to schedule message: {e.response['error']}")
            return None
    
    async def cancel_scheduled_message(self, scheduled_message_id: str) -> bool:
        """Cancel a scheduled message."""
        try:
            if scheduled_message_id in self.scheduled_messages:
                channel = self.scheduled_messages[scheduled_message_id]["channel"]
                
                await self.client.chat_deleteScheduledMessage(
                    channel=channel,
                    scheduled_message_id=scheduled_message_id
                )
                
                del self.scheduled_messages[scheduled_message_id]
                logger.info(f"Cancelled scheduled message {scheduled_message_id}")
                return True
        except SlackApiError as e:
            logger.error(f"Failed to cancel scheduled message: {e.response['error']}")
        
        return False
    
    async def get_channel_id(self, channel_name: str) -> Optional[str]:
        """Get channel ID from channel name."""
        try:
            response = await self.client.conversations_list()
            
            for channel in response["channels"]:
                if channel["name"] == channel_name:
                    return channel["id"]
            
            logger.warning(f"Channel {channel_name} not found")
            return None
        except SlackApiError as e:
            logger.error(f"Failed to get channel ID: {e.response['error']}")
            return None
    
    async def get_user_id(self, email: str) -> Optional[str]:
        """Get user ID from email address."""
        try:
            response = await self.client.users_lookupByEmail(email=email)
            return response["user"]["id"]
        except SlackApiError as e:
            logger.error(f"Failed to get user ID for {email}: {e.response['error']}")
            return None
    
    async def start(self):
        """Start the Slack bot."""
        logger.info("Starting Slack bot...")
        # For Socket Mode, we would start the handler here
        # For HTTP mode, we would start the web server
    
    def _get_help_message(self) -> str:
        """Get help message for slash command."""
        return """
*Fireflies Summary Bot - Help*

Available commands:
• `/fireflies-summary help` - Show this help message
• `/fireflies-summary status` - Show bot status
• `/fireflies-summary subscribe [meeting-series]` - Subscribe to a meeting series
• `/fireflies-summary unsubscribe [meeting-series]` - Unsubscribe from a meeting series

The bot will automatically send you summaries from previous meetings 30 minutes before your scheduled meetings.
        """
    
    def _get_status_message(self) -> str:
        """Get status message for slash command."""
        scheduled_count = len(self.scheduled_messages)
        return f"""
*Fireflies Summary Bot - Status*

✅ Bot is active
📬 Scheduled messages: {scheduled_count}
⏰ Check interval: {config.CHECK_INTERVAL_MINUTES} minutes
🔔 Notification time: {config.NOTIFICATION_MINUTES_BEFORE} minutes before meeting
        """