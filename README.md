# Fireflies Summary Bot

A Slack bot that automatically sends meeting summaries from Fireflies before your upcoming meetings. The bot intelligently identifies meeting series (daily standups, weekly reviews, etc.) and sends relevant context from previous meetings.

## Features

- **Automatic Meeting Detection**: Identifies recurring meeting series using AI-powered pattern recognition
- **Smart Scheduling**: Sends summaries 30 minutes before meetings start
- **Rich Slack Integration**: Beautiful formatted messages with action items, key topics, and participants
- **Calendar Integration**: Supports Google Calendar and Microsoft Outlook
- **Multiple Meeting Patterns**: Handles daily, weekly, bi-weekly, monthly, and ad-hoc meetings
- **Slack Commands**: Interactive commands for managing subscriptions and bot status

## How It Works

1. **Calendar Monitoring**: Every 5 minutes, checks your calendar for upcoming meetings
2. **Series Detection**: Uses advanced pattern matching to group related meetings
3. **Previous Meeting Lookup**: Searches Fireflies for the most recent meeting in the same series
4. **Summary Generation**: Extracts key information (summary, action items, topics, participants)
5. **Slack Delivery**: Sends formatted summary to the appropriate Slack channel

## Installation

### Prerequisites

- Python 3.11+
- Fireflies.ai account with API access
- Slack workspace with bot permissions
- Google Calendar or Outlook calendar access

### Local Development

1. **Clone the repository**
   ```bash
   git clone https://github.com/Poxagronka/fireflies_summary.git
   cd fireflies_summary
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment variables**
   ```bash
   cp .env.example .env
   # Edit .env with your API keys and settings
   ```

4. **Run the bot**
   ```bash
   python -m src.bot
   ```

### Docker Deployment

1. **Build and run with Docker Compose**
   ```bash
   docker-compose up -d
   ```

2. **Or build manually**
   ```bash
   docker build -t fireflies-bot .
   docker run -d --env-file .env -p 8080:8080 fireflies-bot
   ```

## Configuration

### Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `FIREFLIES_API_KEY` | Fireflies.ai API key | ✅ | - |
| `SLACK_BOT_TOKEN` | Slack bot token (xoxb-...) | ✅ | - |
| `SLACK_SIGNING_SECRET` | Slack signing secret | ✅ | - |
| `SLACK_CLIENT_SECRET` | Slack client secret | ✅ | - |
| `NOTIFICATION_MINUTES_BEFORE` | Minutes before meeting to send summary | ❌ | 30 |
| `CHECK_INTERVAL_MINUTES` | How often to check calendar | ❌ | 5 |
| `LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR) | ❌ | INFO |
| `REDIS_URL` | Redis connection URL for caching | ❌ | - |
| `DATABASE_URL` | PostgreSQL URL for user preferences | ❌ | - |

### Slack App Setup

1. **Create a Slack App** at https://api.slack.com/apps
2. **Add Bot Token Scopes**:
   - `channels:read` - List public channels
   - `chat:write` - Send messages
   - `commands` - Handle slash commands
   - `users:read` - Read user information
   - `users:read.email` - Read user email addresses

3. **Add Slash Commands**:
   - `/fireflies-summary help`
   - `/fireflies-summary status`
   - `/fireflies-summary subscribe [series]`
   - `/fireflies-summary unsubscribe [series]`

4. **Install App** to your workspace and copy tokens to `.env`

### Fireflies Setup

1. **Get API Key** from your Fireflies.ai dashboard
2. **Ensure meetings are recorded** and processed by Fireflies
3. **Verify transcript access** in your account settings

### Calendar Integration

#### Google Calendar
1. **Create Google Cloud Project**
2. **Enable Calendar API**
3. **Create OAuth 2.0 credentials**
4. **Download credentials JSON** and set `GOOGLE_CALENDAR_CREDENTIALS`

#### Microsoft Outlook (Optional)
1. **Register Azure AD application**
2. **Configure Calendar.Read permissions**
3. **Set tenant ID, client ID, and secret**

## Usage

### Slack Commands

- **`/fireflies-summary help`** - Show available commands
- **`/fireflies-summary status`** - Display bot status and statistics
- **`/fireflies-summary subscribe [meeting-series]`** - Subscribe to specific meeting series
- **`/fireflies-summary unsubscribe [meeting-series]`** - Unsubscribe from series

### Automatic Operation

The bot runs continuously and:

1. **Monitors Calendar**: Checks every 5 minutes for upcoming meetings
2. **Sends Summaries**: 30 minutes before meetings with previous context
3. **Handles Series**: Groups related meetings automatically
4. **Channel Routing**: Sends to appropriate channels based on meeting content

## Deployment on Fly.io

### Prerequisites

- [Fly.io account](https://fly.io)
- [Fly CLI installed](https://fly.io/docs/hands-on/install-flyctl/)

### Deploy Steps

1. **Login to Fly.io**
   ```bash
   fly auth login
   ```

2. **Launch app**
   ```bash
   fly launch --name fireflies-summary-bot --region iad --no-deploy
   ```

3. **Set secrets**
   ```bash
   fly secrets set \\
     FIREFLIES_API_KEY="your-fireflies-key" \\
     SLACK_BOT_TOKEN="your-slack-token" \\
     SLACK_SIGNING_SECRET="your-signing-secret" \\
     SLACK_CLIENT_SECRET="your-client-secret"
   ```

4. **Deploy**
   ```bash
   fly deploy
   ```

5. **Check status**
   ```bash
   fly status
   fly logs
   ```

### GitHub Actions Auto-Deploy

The repository includes GitHub Actions workflow for automatic deployment:

1. **Add Fly.io token** to GitHub secrets as `FLY_API_TOKEN`
2. **Push to main branch** triggers automatic deployment
3. **Monitor deployment** in Actions tab

## Architecture

### Core Components

- **`bot.py`**: Main orchestrator and web server
- **`fireflies_client.py`**: Fireflies API integration
- **`slack_client.py`**: Slack messaging and commands
- **`calendar_integration.py`**: Calendar APIs (Google/Outlook)
- **`meeting_analyzer.py`**: Meeting series detection and analysis
- **`config.py`**: Configuration management

### Meeting Series Detection

The bot uses sophisticated pattern matching to identify meeting series:

1. **Title Patterns**: Recognizes common meeting formats
2. **Date Intervals**: Analyzes timing patterns (daily, weekly, etc.)
3. **Participant Overlap**: Considers attendee consistency
4. **Topic Similarity**: Matches recurring themes and keywords

### Message Formatting

Slack messages include:

- **Meeting Header**: Title and start time
- **Previous Summary**: Key points from last meeting
- **Action Items**: Outstanding tasks and assignments
- **Key Topics**: Important discussion points
- **Participants**: Attendee list
- **Transcript Link**: Direct link to Fireflies

## Monitoring and Logging

### Health Checks

- **HTTP Endpoint**: `GET /health` returns bot status
- **Fly.io Integration**: Automatic health monitoring
- **Restart Policy**: Auto-restart on failures

### Logging

- **Structured Logging**: JSON format with correlation IDs
- **Log Levels**: Configurable verbosity (DEBUG to ERROR)
- **Error Tracking**: Comprehensive error handling and reporting

### Metrics

Monitor key metrics:
- Meeting summaries sent
- API call success rates
- Calendar sync frequency
- Slack message delivery

## Troubleshooting

### Common Issues

**Bot not sending summaries:**
- Check calendar permissions and API keys
- Verify Fireflies has meeting transcripts
- Confirm Slack bot permissions

**Wrong Slack channels:**
- Adjust channel routing logic in `bot.py`
- Add custom channel mappings
- Check channel permissions

**Missing transcripts:**
- Ensure Fireflies is recording meetings
- Verify meeting titles match patterns
- Check API key permissions

**Calendar not syncing:**
- Refresh OAuth tokens
- Verify calendar permissions
- Check network connectivity

### Debug Mode

Enable debug logging:
```bash
export LOG_LEVEL=DEBUG
python -m src.bot
```

### API Testing

Test individual components:
```bash
# Test Fireflies connection
python -c "from src.fireflies_client import FirefliesClient; print('OK')"

# Test Slack connection
python -c "from src.slack_client import SlackBot; print('OK')"

# Test calendar integration
python -c "from src.calendar_integration import CalendarManager; print('OK')"
```

## Contributing

1. **Fork the repository**
2. **Create feature branch**: `git checkout -b feature/amazing-feature`
3. **Make changes** and add tests
4. **Run tests**: `pytest tests/`
5. **Commit changes**: `git commit -m 'Add amazing feature'`
6. **Push branch**: `git push origin feature/amazing-feature`
7. **Create Pull Request**

### Development Setup

```bash
# Install development dependencies
pip install -r requirements.txt

# Run tests
pytest tests/ -v

# Code formatting
black src/ tests/

# Linting
flake8 src/ tests/
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Support

- **Issues**: [GitHub Issues](https://github.com/Poxagronka/fireflies_summary/issues)
- **Documentation**: [Wiki](https://github.com/Poxagronka/fireflies_summary/wiki)
- **Discussions**: [GitHub Discussions](https://github.com/Poxagronka/fireflies_summary/discussions)

## Roadmap

### Upcoming Features

- **🤖 AI-Powered Summaries**: Enhanced summarization using GPT-4
- **📊 Analytics Dashboard**: Meeting insights and trends
- **🔗 More Integrations**: Teams, Zoom, WebEx support
- **👥 User Preferences**: Personal notification settings
- **📱 Mobile App**: iOS/Android companion app
- **🎯 Smart Routing**: ML-based channel assignment
- **📈 Meeting Metrics**: Productivity analytics
- **🔐 Enterprise SSO**: SAML/OAuth enterprise login

### Version History

- **v1.0.0**: Initial release with core functionality
- **v1.1.0**: Added Microsoft Outlook support
- **v1.2.0**: Enhanced meeting series detection
- **v1.3.0**: Slack interactive commands
- **v2.0.0**: AI-powered summaries and analytics (planned)

---

**Made with ❤️ for better meetings**