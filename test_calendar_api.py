"""
Тестирование Google Apps Script Calendar API
Запусти этот файл для проверки всех endpoint'ов
"""

import requests
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional

class CalendarAPITester:
    def __init__(self):
        self.base_url = "https://script.google.com/macros/s/AKfycbx3xhE0H1souiNBEwryNL6S4UDk_YKkC6LfoGqwDndnAjFYTzSaK-AUVAZgVjfUtOCGAQ/exec"
        self.test_results = []
    
    def test_endpoint(self, name: str, params: Dict = None) -> Dict:
        """Тестирует endpoint и выводит результат"""
        print(f"\n{'='*50}")
        print(f"Тестируем: {name}")
        print(f"Параметры: {params or 'без параметров'}")
        print('-'*50)
        
        try:
            response = requests.get(self.base_url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            # Красивый вывод
            print(f"✅ Успешно!")
            print(f"Статус код: {response.status_code}")
            print(f"Ответ:")
            print(json.dumps(data, indent=2, ensure_ascii=False)[:500])  # Первые 500 символов
            
            if 'events' in data:
                print(f"\nНайдено событий: {len(data['events'])}")
                if data['events']:
                    print(f"Первое событие: {data['events'][0].get('title', 'Без названия')}")
            
            self.test_results.append({
                'test': name,
                'success': True,
                'events_count': len(data.get('events', []))
            })
            
            return data
            
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            self.test_results.append({
                'test': name,
                'success': False,
                'error': str(e)
            })
            return {}
    
    def run_all_tests(self):
        """Запускает все тесты"""
        print("🚀 Начинаем тестирование Calendar API")
        print(f"URL: {self.base_url}")
        
        # Тест 1: Базовый запрос (предстоящие встречи за 24 часа)
        self.test_endpoint("Предстоящие встречи (по умолчанию)")
        
        # Тест 2: Встречи на 48 часов
        self.test_endpoint("Встречи на 48 часов", {'hours': 48})
        
        # Тест 3: Только повторяющиеся встречи
        self.test_endpoint("Повторяющиеся встречи", {'action': 'recurring'})
        
        # Тест 4: Все данные с анализом
        all_data = self.test_endpoint("Все данные с анализом", {'action': 'all'})
        
        # Тест 5: Поиск серии встреч (если есть повторяющиеся)
        if all_data and 'patterns' in all_data:
            # Ищем первую доступную серию
            for pattern_type, meetings in all_data['patterns'].items():
                if meetings:
                    series_name = meetings[0].split()[0]  # Берем первое слово
                    self.test_endpoint(
                        f"История серии '{series_name}'", 
                        {'action': 'series', 'seriesName': series_name}
                    )
                    break
        
        # Итоговый отчет
        self.print_summary()
    
    def check_meetings_in_next_30_minutes(self):
        """Проверяет встречи в ближайшие 30 минут"""
        print(f"\n{'='*50}")
        print("🔍 Проверка встреч в ближайшие 30 минут")
        print('-'*50)
        
        try:
            response = requests.get(self.base_url, params={'hours': 1}, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if 'events' in data:
                now = datetime.now()
                soon = now + timedelta(minutes=30)
                
                upcoming_soon = []
                for event in data['events']:
                    try:
                        start_time = datetime.fromisoformat(event['startTime'].replace('Z', '+00:00'))
                        if now <= start_time <= soon:
                            upcoming_soon.append(event)
                    except (KeyError, ValueError) as e:
                        print(f"Ошибка обработки события: {e}")
                        continue
                
                if upcoming_soon:
                    print(f"⏰ Найдено {len(upcoming_soon)} встреч в ближайшие 30 минут:")
                    for event in upcoming_soon:
                        print(f"  - {event['title']} в {event['startTime']}")
                else:
                    print("Нет встреч в ближайшие 30 минут")
                
                return upcoming_soon
            else:
                print("Не удалось получить события из API")
                return []
                
        except Exception as e:
            print(f"❌ Ошибка при проверке встреч: {e}")
            return []
    
    def find_recurring_patterns(self):
        """Анализирует паттерны повторяющихся встреч"""
        print(f"\n{'='*50}")
        print("📊 Анализ паттернов встреч")
        print('-'*50)
        
        try:
            response = requests.get(self.base_url, params={'action': 'recurring'}, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if 'series' in data:
                print(f"Найдено серий встреч: {len(data['series'])}")
                for series_name, meetings in data['series'].items():
                    print(f"\n📌 Серия: {series_name}")
                    print(f"   Количество: {len(meetings)}")
                    if meetings:
                        print(f"   Следующая: {meetings[0].get('startTime', 'Неизвестно')}")
            
            return data.get('series', {})
            
        except Exception as e:
            print(f"❌ Ошибка при анализе паттернов: {e}")
            return {}
    
    def print_summary(self):
        """Выводит итоговый отчет"""
        print(f"\n{'='*50}")
        print("📈 ИТОГОВЫЙ ОТЧЕТ")
        print('='*50)
        
        successful = sum(1 for r in self.test_results if r['success'])
        failed = len(self.test_results) - successful
        
        print(f"✅ Успешных тестов: {successful}")
        print(f"❌ Проваленных тестов: {failed}")
        
        print("\nДетали:")
        for result in self.test_results:
            status = "✅" if result['success'] else "❌"
            print(f"{status} {result['test']}")
            if result['success'] and 'events_count' in result:
                print(f"   События: {result['events_count']}")
            elif not result['success']:
                print(f"   Ошибка: {result.get('error', 'Неизвестная ошибка')}")

# Запуск тестов
if __name__ == "__main__":
    tester = CalendarAPITester()
    
    # Запускаем все тесты
    tester.run_all_tests()
    
    # Дополнительные проверки
    tester.check_meetings_in_next_30_minutes()
    tester.find_recurring_patterns()
    
    print("\n✨ Тестирование завершено!")