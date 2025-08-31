"""
Отладка Google Apps Script Calendar API
Проверяет что именно возвращает API
"""

import requests
import json

def debug_api_response():
    url = "https://script.google.com/macros/s/AKfycbx3xhE0H1souiNBEwryNL6S4UDk_YKkC6LfoGqwDndnAjFYTzSaK-AUVAZgVjfUtOCGAQ/exec"
    
    print(f"🔍 Тестируем API: {url}")
    
    try:
        print("\n1. Простой GET запрос без параметров:")
        response = requests.get(url, timeout=30)
        print(f"Status Code: {response.status_code}")
        print(f"Headers: {dict(response.headers)}")
        print(f"Content Length: {len(response.text)}")
        print(f"Raw Content (first 500 chars): {response.text[:500]}")
        
        if response.text.strip():
            try:
                data = response.json()
                print(f"JSON успешно распарсен: {json.dumps(data, indent=2, ensure_ascii=False)}")
            except json.JSONDecodeError as e:
                print(f"❌ Ошибка парсинга JSON: {e}")
        else:
            print("❌ Пустой ответ от сервера")
            
    except requests.RequestException as e:
        print(f"❌ Ошибка запроса: {e}")
    
    print("\n" + "="*50)
    
    try:
        print("\n2. GET запрос с параметром hours=24:")
        response = requests.get(url, params={'hours': 24}, timeout=30)
        print(f"Status Code: {response.status_code}")
        print(f"Content Length: {len(response.text)}")
        print(f"Raw Content (first 500 chars): {response.text[:500]}")
        
        if response.text.strip():
            try:
                data = response.json()
                print(f"JSON успешно распарсен: {json.dumps(data, indent=2, ensure_ascii=False)}")
            except json.JSONDecodeError as e:
                print(f"❌ Ошибка парсинга JSON: {e}")
        else:
            print("❌ Пустой ответ от сервера")
            
    except requests.RequestException as e:
        print(f"❌ Ошибка запроса: {e}")
    
    print("\n" + "="*50)
    
    try:
        print("\n3. POST запрос:")
        response = requests.post(url, json={'hours': 24}, timeout=30)
        print(f"Status Code: {response.status_code}")
        print(f"Content Length: {len(response.text)}")
        print(f"Raw Content (first 500 chars): {response.text[:500]}")
        
        if response.text.strip():
            try:
                data = response.json()
                print(f"JSON успешно распарсен: {json.dumps(data, indent=2, ensure_ascii=False)}")
            except json.JSONDecodeError as e:
                print(f"❌ Ошибка парсинга JSON: {e}")
        else:
            print("❌ Пустой ответ от сервера")
            
    except requests.RequestException as e:
        print(f"❌ Ошибка запроса: {e}")

if __name__ == "__main__":
    debug_api_response()