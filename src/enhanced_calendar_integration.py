"""
Enhanced calendar integration that combines multiple sources:
1. Google Apps Script API (Appodeal specific)
2. Original Google Calendar API
3. Fallback mock data for testing
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from .google_calendar_integration import GoogleCalendarClient
from .calendar_integration import CalendarManager, CalendarEvent

logger = logging.getLogger(__name__)

@dataclass
class EnhancedCalendarEvent:
    """Enhanced calendar event with additional metadata"""
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
    source: str  # 'apps_script', 'google_api', 'mock'
    minutes_until_start: Optional[int] = None

class EnhancedCalendarManager:
    """Enhanced calendar manager with multiple data sources"""
    
    def __init__(self):
        self.apps_script_client = None
        self.google_api_manager = CalendarManager()
        
        # Попытаемся подключить Google Apps Script
        try:
            self.apps_script_client = GoogleCalendarClient()
        except Exception as e:
            logger.warning(f"Google Apps Script недоступен: {e}")
            self.apps_script_client = None
    
    async def get_upcoming_events_multiple_sources(
        self,
        minutes_ahead: int = 30
    ) -> List[EnhancedCalendarEvent]:
        """
        Получает события из всех доступных источников и объединяет их
        """
        all_events = []
        
        # 1. Пытаемся получить из Google Apps Script (приоритет)
        if self.apps_script_client:
            try:
                apps_script_events = await self.apps_script_client.get_meetings_starting_soon(minutes_ahead)
                
                for event in apps_script_events:
                    enhanced_event = self._convert_apps_script_event(event)
                    if enhanced_event:
                        all_events.append(enhanced_event)
                        
                logger.info(f"Получено {len(apps_script_events)} событий из Apps Script")
                
            except Exception as e:
                logger.error(f"Ошибка получения событий из Apps Script: {e}")
        
        # 2. Если Apps Script не сработал или дал мало событий, используем Google Calendar API
        if len(all_events) == 0:
            try:
                time_min = datetime.now()
                time_max = time_min + timedelta(minutes=minutes_ahead + 10)
                
                google_events = await self.google_api_manager.get_all_upcoming_events(time_min, time_max)
                
                for event in google_events:
                    enhanced_event = self._convert_google_api_event(event, minutes_ahead)
                    if enhanced_event:
                        all_events.append(enhanced_event)
                        
                logger.info(f"Получено {len(google_events)} событий из Google Calendar API")
                
            except Exception as e:
                logger.error(f"Ошибка получения событий из Google Calendar API: {e}")
        
        # 3. Если ничего не получилось, создаем тестовые данные (для демо)
        if len(all_events) == 0:
            logger.warning("Не удалось получить события ни из одного источника, создаем тестовые данные")
            all_events = self._create_mock_events(minutes_ahead)
        
        # Убираем дубликаты и сортируем
        unique_events = self._remove_duplicates(all_events)
        unique_events.sort(key=lambda x: x.start_time)
        
        logger.info(f"Итого уникальных событий: {len(unique_events)}")
        
        return unique_events
    
    async def find_previous_meeting_in_series(
        self,
        meeting_title: str
    ) -> Optional[Dict[str, Any]]:
        """Ищет предыдущую встречу в серии из всех источников"""
        
        # 1. Сначала пробуем Apps Script (если доступен)
        if self.apps_script_client:
            try:
                previous = await self.apps_script_client.get_previous_meeting_in_series(meeting_title)
                if previous:
                    logger.info(f"Найдена предыдущая встреча через Apps Script: {previous.get('title', 'Без названия')}")
                    return previous
            except Exception as e:
                logger.error(f"Ошибка поиска через Apps Script: {e}")
        
        # 2. Fallback к анализу по стандартному алгоритму
        logger.info(f"Поиск предыдущей встречи для '{meeting_title}' через анализ названий")
        
        # Здесь можно добавить логику поиска через Fireflies или другие источники
        # Пока возвращаем None
        return None
    
    def _convert_apps_script_event(self, event: Dict) -> Optional[EnhancedCalendarEvent]:
        """Конвертирует событие из Apps Script в EnhancedCalendarEvent"""
        try:
            start_str = event.get('startTime', '')
            if not start_str:
                return None
                
            # Парсим время
            if start_str.endswith('Z'):
                start_time = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
            else:
                start_time = datetime.fromisoformat(start_str)
            
            # Вычисляем время окончания (по умолчанию +1 час)
            end_str = event.get('endTime')
            if end_str:
                if end_str.endswith('Z'):
                    end_time = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
                else:
                    end_time = datetime.fromisoformat(end_str)
            else:
                end_time = start_time + timedelta(hours=1)
            
            return EnhancedCalendarEvent(
                id=event.get('id', f"apps_script_{hash(event.get('title', ''))}"),
                title=event.get('title', 'Untitled Meeting'),
                start_time=start_time,
                end_time=end_time,
                attendees=event.get('attendees', []),
                description=event.get('description', ''),
                location=event.get('location', ''),
                meeting_url=event.get('meetingUrl', event.get('hangoutLink', '')),
                is_recurring=event.get('isRecurring', False),
                series_id=event.get('seriesId'),
                source='apps_script',
                minutes_until_start=event.get('minutes_until_start')
            )
            
        except Exception as e:
            logger.error(f"Ошибка конвертации Apps Script события: {e}")
            return None
    
    def _convert_google_api_event(
        self,
        event: CalendarEvent,
        minutes_ahead: int
    ) -> Optional[EnhancedCalendarEvent]:
        """Конвертирует событие из Google Calendar API в EnhancedCalendarEvent"""
        try:
            now = datetime.now(event.start_time.tzinfo or datetime.now().astimezone().tzinfo)
            time_until = (event.start_time - now).total_seconds() / 60
            
            # Проверяем, что событие в нужном временном окне
            if not (0 < time_until <= minutes_ahead):
                return None
            
            return EnhancedCalendarEvent(
                id=event.id,
                title=event.title,
                start_time=event.start_time,
                end_time=event.end_time,
                attendees=event.attendees,
                description=event.description,
                location=event.location,
                meeting_url=event.meeting_url,
                is_recurring=event.is_recurring,
                series_id=event.series_id,
                source='google_api',
                minutes_until_start=int(time_until)
            )
            
        except Exception as e:
            logger.error(f"Ошибка конвертации Google API события: {e}")
            return None
    
    def _create_mock_events(self, minutes_ahead: int) -> List[EnhancedCalendarEvent]:
        """Создает тестовые события для демонстрации"""
        mock_events = []
        
        # Создаем тестовую встречу через 25 минут
        if minutes_ahead >= 25:
            start_time = datetime.now() + timedelta(minutes=25)
            mock_events.append(EnhancedCalendarEvent(
                id="mock_daily_standup",
                title="Daily Standup",
                start_time=start_time,
                end_time=start_time + timedelta(minutes=30),
                attendees=["alice@example.com", "bob@example.com"],
                description="Daily team standup meeting",
                location="Zoom",
                meeting_url="https://zoom.us/j/123456789",
                is_recurring=True,
                series_id="daily_standup_series",
                source="mock",
                minutes_until_start=25
            ))
        
        # Создаем тестовую встречу через 20 минут
        if minutes_ahead >= 20:
            start_time = datetime.now() + timedelta(minutes=20)
            mock_events.append(EnhancedCalendarEvent(
                id="mock_product_review",
                title="Product Review Meeting",
                start_time=start_time,
                end_time=start_time + timedelta(hours=1),
                attendees=["pm@example.com", "dev@example.com"],
                description="Weekly product review",
                location="Conference Room A",
                meeting_url="https://meet.google.com/abc-def-ghi",
                is_recurring=True,
                series_id="product_review_series",
                source="mock",
                minutes_until_start=20
            ))
        
        return mock_events
    
    def _remove_duplicates(self, events: List[EnhancedCalendarEvent]) -> List[EnhancedCalendarEvent]:
        """Удаляет дублирующиеся события по названию и времени"""
        seen = set()
        unique_events = []
        
        for event in events:
            # Создаем ключ для дедупликации
            key = (event.title.lower().strip(), event.start_time.isoformat())
            
            if key not in seen:
                seen.add(key)
                unique_events.append(event)
            else:
                logger.debug(f"Пропускаем дубликат: {event.title}")
        
        return unique_events

# Пример использования
async def test_enhanced_calendar():
    """Тестирование enhanced calendar manager"""
    logging.basicConfig(level=logging.INFO)
    
    manager = EnhancedCalendarManager()
    
    print("🔍 Поиск встреч в ближайшие 30 минут...")
    events = await manager.get_upcoming_events_multiple_sources(30)
    
    if events:
        print(f"\n✅ Найдено {len(events)} событий:")
        for event in events:
            print(f"📅 {event.title}")
            print(f"   ⏰ Через {event.minutes_until_start} минут")
            print(f"   🔗 {event.meeting_url or 'Нет ссылки'}")
            print(f"   📍 Источник: {event.source}")
            
            # Ищем предыдущую встречу
            previous = await manager.find_previous_meeting_in_series(event.title)
            if previous:
                print(f"   📋 Предыдущая встреча найдена: {previous.get('title', 'Без названия')}")
            else:
                print(f"   📋 Предыдущая встреча не найдена")
            print()
    else:
        print("❌ События не найдены")

if __name__ == "__main__":
    asyncio.run(test_enhanced_calendar())