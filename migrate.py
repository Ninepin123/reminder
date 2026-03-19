import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo
import mysql.connector
from mysql.connector import Error
from dotenv import load_dotenv

load_dotenv()

TZ = ZoneInfo("Asia/Taipei")

MYSQL_HOST = os.getenv('MYSQL_HOST', 'localhost')
MYSQL_PORT = int(os.getenv('MYSQL_PORT', 3306))
MYSQL_USER = os.getenv('MYSQL_USER')
MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD')
MYSQL_DATABASE = os.getenv('MYSQL_DATABASE')

JSON_FILE = "reminders.json"

def get_db_connection():
    try:
        conn = mysql.connector.connect(
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DATABASE,
            charset='utf8mb4'
        )
        return conn
    except Error as e:
        print(f"資料庫連線錯誤: {e}")
        return None

def migrate():
    conn = get_db_connection()
    if not conn:
        print("❌ 無法連線到資料庫")
        return

    cursor = conn.cursor()

    # 建立資料表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reminders (
            id INT AUTO_INCREMENT PRIMARY KEY,
            channel_id BIGINT NOT NULL,
            message TEXT NOT NULL,
            time DATETIME NOT NULL,
            user_id BIGINT NOT NULL,
            guild_id BIGINT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_reminders (
            id INT AUTO_INCREMENT PRIMARY KEY,
            channel_id BIGINT NOT NULL,
            message TEXT NOT NULL,
            time VARCHAR(5) NOT NULL,
            user_id BIGINT NOT NULL,
            guild_id BIGINT,
            created_at DATETIME,
            last_triggered_date DATE
        )
    ''')

    # 嘗試新增 last_triggered_date 欄位 (相容已存在的表)
    try:
        cursor.execute("ALTER TABLE daily_reminders ADD COLUMN last_triggered_date DATE")
    except Error:
        pass

    conn.commit()

    # 讀取 JSON
    try:
        with open(JSON_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print("找不到 reminders.json，跳過資料遷移")
        cursor.close()
        conn.close()
        return

    # 遷移一次性提醒
    reminders_count = 0
    for r in data.get('reminders', []):
        try:
            cursor.execute('''
                INSERT INTO reminders (channel_id, message, time, user_id, guild_id)
                VALUES (%s, %s, %s, %s, %s)
            ''', (r['channel_id'], r['message'], r['time'], r['user_id'], r['guild_id']))
            reminders_count += 1
        except Exception as e:
            print(f"遷移提醒失敗: {e}")

    # 遷移每日提醒
    daily_count = 0
    for d in data.get('daily_reminders', []):
        try:
            cursor.execute('''
                INSERT INTO daily_reminders (channel_id, message, time, user_id, guild_id, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (d['channel_id'], d['message'], d['time'], d['user_id'], d.get('guild_id'), d.get('created_at')))
            daily_count += 1
        except Exception as e:
            print(f"遷移每日提醒失敗: {e}")

    conn.commit()
    cursor.close()
    conn.close()

    print(f"✅ 遷移完成！")
    print(f"   一次性提醒: {reminders_count} 個")
    print(f"   每日提醒: {daily_count} 個")

if __name__ == "__main__":
    migrate()
