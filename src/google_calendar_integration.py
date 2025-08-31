"""
Интеграция с Google Calendar через Apps Script API
Используй этот модуль в основном боте
"""

import requests
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
import logging
import re
import asyncio
import aiohttp

logger = logging.getLogger(__name__)

class GoogleCalendarClient:
    def __init__(self):
        self.api_url = "https://script.google.com/macros/s/AKfycbx3xhE0H1souiNBEwryNL6S4UDk_YKkC6LfoGqwDndnAjFYTzSaK-AUVAZgVjfUtOCGAQ/exec"
        self.connection_ok = self._test_connection()
    
    def _test_connection(self):
        """Проверяет доступность API при инициализации"""
        try:
            response = requests.get(self.api_url, params={'hours': 1}, timeout=10)
            response.raise_for_status()
            
            # Проверяем, не редирект ли на авторизацию
            if 'Sign in - Google Accounts' in response.text or 'accounts/AccountChooser' in response.text:
                logger.error("❌ Google Apps Script требует авторизации. Необходимо сделать скрипт публичным или настроить авторизацию.")
                logger.error("📋 Инструкция: откройте скрипт в Google Apps Script, перейдите в Deploy > Manage deployments > Edit > Execute as: Me, Who has access: Anyone")
                return False
            
            # Пытаемся распарсить JSON
            try:
                data = response.json()
                if data.get('success', True):
                    logger.info("✅ Google Calendar API подключен успешно")
                    return True
                else:
                    logger.error(f"❌ API вернул ошибку: {data.get('error', 'Неизвестная ошибка')}")
                    return False
            except:
                logger.error(f"❌ API вернул не JSON ответ. Возможно, требуется авторизация.")
                return False
                
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к Calendar API: {e}")
            return False
    
    async def get_meetings_starting_soon(self, minutes_ahead: int = 30) -> List[Dict]:
        """
        Получает встречи, которые начнутся в ближайшие N минут
        
        Args:
            minutes_ahead: За сколько минут до встречи искать
            
        Returns:
            Список встреч, которые скоро начнутся
        """
        try:
            # Используем aiohttp для асинхронных запросов
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.api_url, 
                    params={'hours': 2},  # Запрашиваем на 2 часа для большей надежности
                    timeout=aiohttp.ClientTimeout(total=30),
                    allow_redirects=True  # Разрешаем редиректы для Google Apps Script
                ) as response:
                    response.raise_for_status()
                    data = await response.json()
            
            if not data.get('success', True):
                logger.error(f"API вернул ошибку: {data.get('error')}")
                return []
            
            meetings_soon = []
            now = datetime.now(timezone.utc)  # Use UTC timezone
            threshold = now + timedelta(minutes=minutes_ahead)
            
            for event in data.get('events', []):
                try:
                    # Парсим время начала
                    start_str = event.get('startTime', '')
                    if not start_str:
                        continue
                        
                    # Поддерживаем разные форматы времени
                    if start_str.endswith('Z'):
                        start_time = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                    else:
                        start_time = datetime.fromisoformat(start_str)
                        if start_time.tzinfo is None:
                            start_time = start_time.replace(tzinfo=timezone.utc)
                    
                    # Проверяем, попадает ли в наш временной диапазон
                    time_until_seconds = (start_time - now).total_seconds()
                    time_until_minutes = time_until_seconds / 60
                    
                    # Встреча должна быть в будущем и в пределах нашего окна
                    if 0 < time_until_minutes <= minutes_ahead:
                        event['minutes_until_start'] = int(time_until_minutes)
                        event['seconds_until_start'] = int(time_until_seconds)
                        meetings_soon.append(event)
                        logger.info(f"Найдена встреча '{event.get('title', 'Без названия')}' через {int(time_until_minutes)} минут")
                        
                except Exception as e:
                    logger.warning(f"Ошибка обработки события {event}: {e}")
                    continue
            
            return meetings_soon
            
        except Exception as e:
            logger.error(f"Ошибка получения встреч: {e}")
            return []
    
    async def get_previous_meeting_in_series(self, meeting_title: str) -> Optional[Dict]:
        """
        Находит предыдущую встречу из той же серии
        
        Args:
            meeting_title: Название встречи для поиска серии
            
        Returns:
            Данные предыдущей встречи или None
        """
        try:
            # Извлекаем ключевые слова из названия
            series_name = self._extract_series_name(meeting_title)
            
            logger.info(f"Ищем предыдущую встречу для серии: '{series_name}' из названия '{meeting_title}'")
            
            # Запрашиваем историю серии
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.api_url,
                    params={
                        'action': 'series',
                        'seriesName': series_name
                    },
                    timeout=aiohttp.ClientTimeout(total=30),
                    allow_redirects=True
                ) as response:
                    response.raise_for_status()
                    data = await response.json()
            
            if data.get('success', True) and data.get('lastMeeting'):
                logger.info(f"✅ Найдена предыдущая встреча: {data['lastMeeting'].get('title', 'Без названия')}")
                return data['lastMeeting']
            else:
                logger.warning(f"Предыдущая встреча не найдена для серии: {series_name}")
                
                # Попробуем более общий поиск
                return await self._fallback_search(meeting_title)
                
        except Exception as e:
            logger.error(f"Ошибка поиска предыдущей встречи: {e}")
            return None
    
    async def _fallback_search(self, meeting_title: str) -> Optional[Dict]:
        """Резервный поиск по всем повторяющимся встречам"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.api_url,
                    params={'action': 'recurring'},
                    timeout=aiohttp.ClientTimeout(total=30),
                    allow_redirects=True
                ) as response:
                    response.raise_for_status()
                    data = await response.json()
            
            # Ищем похожие названия в сериях
            title_words = set(meeting_title.lower().split())
            
            for series_name, meetings in data.get('series', {}).items():
                series_words = set(series_name.lower().split())
                
                # Проверяем пересечение слов (схожесть названий)
                if len(title_words & series_words) >= 1 and meetings:
                    logger.info(f"Найдена похожая серия: {series_name}")
                    return meetings[-1]  # Последняя встреча в серии
            
            return None
            
        except Exception as e:
            logger.error(f"Ошибка резервного поиска: {e}")
            return None
    
    async def get_recurring_patterns(self) -> Dict[str, List]:
        """
        Получает все паттерны повторяющихся встреч
        
        Returns:
            Словарь с паттернами встреч
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.api_url, 
                    params={'action': 'all'},
                    timeout=aiohttp.ClientTimeout(total=30),
                    allow_redirects=True
                ) as response:
                    response.raise_for_status()
                    data = await response.json()
            
            if data.get('success', True):
                patterns = data.get('patterns', {})
                logger.info(f"Найдено паттернов: daily={len(patterns.get('daily', []))}, "
                          f"weekly={len(patterns.get('weekly', []))}")
                return patterns
            
            return {}
            
        except Exception as e:
            logger.error(f"Ошибка получения паттернов: {e}")
            return {}
    
    def _extract_series_name(self, title: str) -> str:
        """Извлекает название серии из полного названия встречи"""
        # Удаляем даты в различных форматах
        cleaned = re.sub(r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}', '', title)
        cleaned = re.sub(r'\d{4}[/-]\d{1,2}[/-]\d{1,2}', '', cleaned)
        
        # Удаляем номера эпизодов/сессий
        cleaned = re.sub(r'#\d+', '', cleaned)
        cleaned = re.sub(r'№\d+', '', cleaned)
        cleaned = re.sub(r'\b\d+\b', '', cleaned)
        
        # Удаляем лишние пробелы
        cleaned = re.sub(r'\s+', ' ', cleaned)
        
        # Берем первые 2-4 слова как идентификатор серии
        words = cleaned.strip().split()[:4]
        series_name = ' '.join(words).strip()
        
        # Если название слишком короткое, берем оригинальное
        if len(series_name) < 3:
            words = title.split()[:3]
            series_name = ' '.join(words)
        
        return series_name
    
    async def get_upcoming_events(self, minutes_ahead: int = 30) -> List[Dict]:
        """
        Получает все предстоящие встречи в указанном временном диапазоне
        
        Args:
            minutes_ahead: За сколько минут вперед искать встречи
            
        Returns:
            Список предстоящих встреч
        """
        try:
            hours_ahead = max(2, int(minutes_ahead / 60))  # Минимум 2 часа
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.api_url, 
                    params={'hours': hours_ahead},
                    timeout=aiohttp.ClientTimeout(total=30),
                    allow_redirects=True
                ) as response:
                    response.raise_for_status()
                    data = await response.json()
            
            if not data.get('success', True):
                logger.error(f"API вернул ошибку: {data.get('error')}")
                return []
            
            upcoming_events = []
            now = datetime.now(timezone.utc)
            
            for event in data.get('events', []):
                try:
                    # Парсим время начала
                    start_str = event.get('startTime', '')
                    if not start_str:
                        continue
                        
                    if start_str.endswith('Z'):
                        start_time = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                    else:
                        start_time = datetime.fromisoformat(start_str)
                        if start_time.tzinfo is None:
                            start_time = start_time.replace(tzinfo=timezone.utc)
                    
                    # Включаем все будущие встречи в указанном диапазоне
                    time_until_seconds = (start_time - now).total_seconds()
                    time_until_minutes = time_until_seconds / 60
                    
                    if 0 < time_until_minutes <= minutes_ahead:
                        event['minutes_until_start'] = int(time_until_minutes)
                        event['seconds_until_start'] = int(time_until_seconds)
                        upcoming_events.append(event)
                        logger.info(f"Найдена предстоящая встреча '{event.get('title', 'Без названия')}' через {int(time_until_minutes)} минут")
                        
                except Exception as e:
                    logger.warning(f"Ошибка обработки события {event}: {e}")
                    continue
            
            return upcoming_events
            
        except Exception as e:
            logger.error(f"Ошибка получения предстоящих встреч: {e}")
            return []

    async def test_api(self) -> bool:
        """
        Тестирует доступность и работоспособность API
        
        Returns:
            True если API работает, False если нет
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.api_url, 
                    timeout=aiohttp.ClientTimeout(total=10),
                    allow_redirects=True
                ) as response:
                    response.raise_for_status()
                    data = await response.json()
                    return data.get('success', True)
                    
        except Exception as e:
            logger.error(f"Тест API провален: {e}")
            return False

# Пример использования в боте
async def main():
    """Пример использования"""
    # Настрой логирование
    logging.basicConfig(level=logging.INFO)
    
    # Создай клиент
    calendar = GoogleCalendarClient()
    
    # Проверь встречи в ближайшие 30 минут
    upcoming = await calendar.get_meetings_starting_soon(30)
    
    if upcoming:
        print(f"\n🔔 Встречи в ближайшие 30 минут:")
        for meeting in upcoming:
            print(f"  - {meeting.get('title', 'Без названия')} через {meeting['minutes_until_start']} мин")
            
            # Найди предыдущую встречу из серии
            previous = await calendar.get_previous_meeting_in_series(meeting['title'])
            if previous:
                print(f"    Предыдущая встреча была: {previous.get('date', previous.get('startTime', 'Неизвестно'))}")
            else:
                print(f"    Предыдущая встреча не найдена")
    else:
        print("Нет встреч в ближайшие 30 минут")

if __name__ == "__main__":
    asyncio.run(main())