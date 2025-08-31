"""Tests for the main bot functionality."""

import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch, AsyncMock

from src.bot import FirefliesSummaryBot
from src.fireflies_client import Transcript
from src.calendar_integration import CalendarEvent
from src.meeting_analyzer import MeetingAnalyzer


@pytest.fixture
def bot():
    """Create a bot instance for testing."""
    with patch('src.bot.config') as mock_config:
        mock_config.FIREFLIES_API_KEY = "test_key"
        mock_config.SLACK_BOT_TOKEN = "test_token"
        mock_config.SLACK_SIGNING_SECRET = "test_secret"
        mock_config.CHECK_INTERVAL_MINUTES = 1
        mock_config.NOTIFICATION_MINUTES_BEFORE = 30
        mock_config.HOST = "localhost"
        mock_config.PORT = 8080
        
        bot = FirefliesSummaryBot()
        return bot


@pytest.fixture
def sample_event():
    """Create a sample calendar event."""
    return CalendarEvent(
        id="test_event_123",
        title="Daily Standup",
        start_time=datetime.now(timezone.utc) + timedelta(minutes=30),
        end_time=datetime.now(timezone.utc) + timedelta(minutes=60),
        attendees=["alice@example.com", "bob@example.com"],
        description="Team daily standup meeting",
        location="Conference Room A",
        meeting_url="https://meet.google.com/abc-def-ghi",
        is_recurring=True,
        series_id="standup_series"
    )


@pytest.fixture
def sample_transcript():
    """Create a sample transcript."""
    return Transcript(
        id="transcript_123",
        title="Daily Standup - Yesterday",
        date=datetime.now(timezone.utc) - timedelta(days=1),
        duration_minutes=15,
        summary="Team discussed progress on current sprint tasks. All tasks are on track.",
        action_items=[
            "Alice to review PR #123",
            "Bob to update documentation"
        ],
        participants=["Alice", "Bob", "Charlie"],
        meeting_url="https://app.fireflies.ai/view/transcript_123",
        transcript_text="Alice: Good morning everyone...",
        key_topics=["sprint progress", "code review", "documentation"]
    )


class TestFirefliesSummaryBot:
    """Test cases for FirefliesSummaryBot."""
    
    @pytest.mark.asyncio
    async def test_bot_initialization(self, bot):
        """Test bot initializes correctly."""
        assert bot.fireflies_client is not None
        assert bot.slack_bot is not None
        assert bot.calendar_manager is not None
        assert bot.meeting_analyzer is not None
        assert not bot.running
        assert len(bot.processed_events) == 0
    
    @pytest.mark.asyncio
    async def test_health_check(self, bot):
        """Test health check endpoint."""
        from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop
        from aiohttp import web
        
        request = Mock()
        response = await bot.health_check(request)
        
        assert response.status == 200
        assert "status" in response.body
    
    @pytest.mark.asyncio
    async def test_determine_slack_channel(self, bot, sample_event):
        """Test Slack channel determination logic."""
        with patch.object(bot.slack_bot, 'get_channel_id', new_callable=AsyncMock) as mock_get_channel:
            mock_get_channel.return_value = "channel_123"
            
            # Test engineering channel
            sample_event.title = "Engineering Daily Standup"
            channel = await bot.determine_slack_channel(sample_event)
            mock_get_channel.assert_called_with("engineering")
            
            # Test product channel
            sample_event.title = "Product Planning Meeting"
            channel = await bot.determine_slack_channel(sample_event)
            mock_get_channel.assert_called_with("product")
            
            # Test default channel
            sample_event.title = "Random Meeting"
            with patch.object(bot.slack_bot, 'get_channel_id', 
                            side_effect=[None, "default_channel"]) as mock_fallback:
                channel = await bot.determine_slack_channel(sample_event)
                assert mock_fallback.call_count == 2
    
    @pytest.mark.asyncio
    async def test_process_event_with_previous_meeting(self, bot, sample_event, sample_transcript):
        """Test processing an event with a previous meeting."""
        with patch.object(bot.fireflies_client, '__aenter__', new_callable=AsyncMock) as mock_client_enter:
            mock_client = Mock()
            mock_client.find_previous_meeting_in_series = AsyncMock(return_value=sample_transcript)
            mock_client_enter.return_value = mock_client
            
            with patch.object(bot, 'send_summary_to_slack', new_callable=AsyncMock) as mock_send_summary:
                await bot.process_event(sample_event)
                
                mock_send_summary.assert_called_once_with(sample_event, sample_transcript)
    
    @pytest.mark.asyncio
    async def test_process_event_first_meeting(self, bot, sample_event):
        """Test processing the first meeting in a series."""
        with patch.object(bot.fireflies_client, '__aenter__', new_callable=AsyncMock) as mock_client_enter:
            mock_client = Mock()
            mock_client.find_previous_meeting_in_series = AsyncMock(return_value=None)
            mock_client_enter.return_value = mock_client
            
            with patch.object(bot, 'send_first_meeting_notification', new_callable=AsyncMock) as mock_send_first:
                await bot.process_event(sample_event)
                
                mock_send_first.assert_called_once_with(sample_event)
    
    @pytest.mark.asyncio
    async def test_send_summary_to_slack(self, bot, sample_event, sample_transcript):
        """Test sending summary to Slack."""
        with patch.object(bot, 'determine_slack_channel', new_callable=AsyncMock) as mock_channel:
            mock_channel.return_value = "test_channel"
            
            with patch.object(bot.slack_bot, 'send_meeting_summary', new_callable=AsyncMock) as mock_send:
                mock_send.return_value = "1234567890.123"
                
                await bot.send_summary_to_slack(sample_event, sample_transcript)
                
                mock_send.assert_called_once()
                args = mock_send.call_args[1]
                
                assert args['channel'] == "test_channel"
                assert args['meeting_title'] == sample_event.title
                assert args['summary'] == sample_transcript.summary
                assert args['action_items'] == sample_transcript.action_items
    
    @pytest.mark.asyncio
    async def test_check_upcoming_meetings(self, bot, sample_event):
        """Test checking for upcoming meetings."""
        with patch.object(bot.calendar_manager, 'get_events_starting_soon', new_callable=AsyncMock) as mock_get_events:
            mock_get_events.return_value = [sample_event]
            
            with patch.object(bot, 'process_event', new_callable=AsyncMock) as mock_process:
                await bot.check_upcoming_meetings()
                
                mock_get_events.assert_called_once()
                mock_process.assert_called_once_with(sample_event)
                
                # Verify event is marked as processed
                event_key = f"{sample_event.id}_{sample_event.start_time.isoformat()}"
                assert event_key in bot.processed_events
    
    @pytest.mark.asyncio
    async def test_processed_events_deduplication(self, bot, sample_event):
        """Test that processed events are not processed again."""
        event_key = f"{sample_event.id}_{sample_event.start_time.isoformat()}"
        bot.processed_events.add(event_key)
        
        with patch.object(bot.calendar_manager, 'get_events_starting_soon', new_callable=AsyncMock) as mock_get_events:
            mock_get_events.return_value = [sample_event]
            
            with patch.object(bot, 'process_event', new_callable=AsyncMock) as mock_process:
                await bot.check_upcoming_meetings()
                
                # process_event should not be called since event is already processed
                mock_process.assert_not_called()
    
    def test_cleanup_processed_events(self, bot):
        """Test cleanup of old processed events."""
        now = datetime.now(timezone.utc)
        
        # Add recent and old events
        recent_event = f"recent_{(now - timedelta(hours=1)).isoformat()}"
        old_event = f"old_{(now - timedelta(days=2)).isoformat()}"
        
        bot.processed_events.add(recent_event)
        bot.processed_events.add(old_event)
        
        bot._cleanup_processed_events()
        
        # Only recent event should remain
        assert recent_event in bot.processed_events
        assert old_event not in bot.processed_events


class TestMeetingAnalyzer:
    """Test cases for MeetingAnalyzer."""
    
    def test_extract_series_name(self):
        """Test extracting series names from meeting titles."""
        analyzer = MeetingAnalyzer()
        
        # Test various patterns
        assert analyzer.extract_series_name("Daily Standup") == "daily standup"
        assert analyzer.extract_series_name("Weekly Team Meeting") == "weekly team meeting"
        assert analyzer.extract_series_name("Sprint Planning 10/15") is not None
        assert analyzer.extract_series_name("[Project Alpha] Status Update") == "Project Alpha"
        assert analyzer.extract_series_name("Engineering Sync: Sprint 23") == "Engineering Sync"
    
    def test_detect_meeting_pattern(self):
        """Test detecting meeting recurrence patterns."""
        analyzer = MeetingAnalyzer()
        
        # Create meetings with different intervals
        base_date = datetime.now(timezone.utc)
        
        # Daily meetings
        daily_meetings = [
            {"date": base_date - timedelta(days=i), "title": "Daily Standup"}
            for i in range(5)
        ]
        assert analyzer.detect_meeting_pattern(daily_meetings) == "daily"
        
        # Weekly meetings
        weekly_meetings = [
            {"date": base_date - timedelta(weeks=i), "title": "Weekly Review"}
            for i in range(4)
        ]
        assert analyzer.detect_meeting_pattern(weekly_meetings) == "weekly"
        
        # Single meeting
        single_meeting = [{"date": base_date, "title": "One-time Meeting"}]
        assert analyzer.detect_meeting_pattern(single_meeting) == "adhoc"
    
    def test_extract_series_key(self):
        """Test extracting series keys for grouping."""
        analyzer = MeetingAnalyzer()
        
        meeting1 = {"title": "Daily Standup 10/15/2023"}
        meeting2 = {"title": "Daily Standup 10/16/2023"}
        meeting3 = {"title": "Weekly Planning"}
        
        key1 = analyzer.extract_series_key(meeting1)
        key2 = analyzer.extract_series_key(meeting2)
        key3 = analyzer.extract_series_key(meeting3)
        
        # Same series should have same key
        assert key1 == key2
        # Different series should have different keys
        assert key1 != key3
    
    def test_find_previous_in_series(self):
        """Test finding previous meeting in series."""
        analyzer = MeetingAnalyzer()
        
        base_date = datetime.now(timezone.utc)
        meetings = [
            {
                "title": "Daily Standup",
                "date": (base_date - timedelta(days=2)).isoformat()
            },
            {
                "title": "Daily Standup",
                "date": (base_date - timedelta(days=1)).isoformat()
            },
            {
                "title": "Weekly Planning",
                "date": (base_date - timedelta(days=1)).isoformat()
            }
        ]
        
        # Find previous standup
        previous = analyzer.find_previous_in_series(
            "Daily Standup",
            base_date,
            meetings
        )
        
        assert previous is not None
        assert previous["title"] == "Daily Standup"
        # Should be the most recent one (1 day ago, not 2 days ago)
        assert (base_date - timedelta(days=1)).isoformat() in previous["date"]


if __name__ == "__main__":
    pytest.main([__file__])