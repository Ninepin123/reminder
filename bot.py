import os
import asyncio
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional
import mysql.connector
from mysql.connector import Error
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()

# 使用台灣時區
TZ = ZoneInfo("Asia/Taipei")

# MySQL 連線設定
MYSQL_HOST = os.getenv('MYSQL_HOST', 'localhost')
MYSQL_PORT = int(os.getenv('MYSQL_PORT', 3306))
MYSQL_USER = os.getenv('MYSQL_USER')
MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD')
MYSQL_DATABASE = os.getenv('MYSQL_DATABASE')

def get_db_connection():
    """取得資料庫連線"""
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

def init_db():
    """初始化資料庫"""
    conn = get_db_connection()
    if not conn:
        return False

    try:
        cursor = conn.cursor()

        # 一次性提醒表
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

        # 每日提醒表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_reminders (
                id INT AUTO_INCREMENT PRIMARY KEY,
                channel_id BIGINT NOT NULL,
                message TEXT NOT NULL,
                time VARCHAR(5) NOT NULL,
                user_id BIGINT NOT NULL,
                guild_id BIGINT,
                created_at DATETIME
            )
        ''')

        conn.commit()
        return True
    finally:
        conn.close()

def add_reminder(channel_id: int, message: str, reminder_time: datetime, user_id: int, guild_id: int):
    """新增一次性提醒"""
    conn = get_db_connection()
    if not conn:
        return False

    try:
        # 將帶時區的 datetime 轉換為 naive datetime，確保存儲一致性
        time_naive = reminder_time.replace(tzinfo=None) if reminder_time.tzinfo else reminder_time

        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO reminders (channel_id, message, time, user_id, guild_id)
            VALUES (%s, %s, %s, %s, %s)
        ''', (channel_id, message, time_naive, user_id, guild_id))
        conn.commit()
        return True
    finally:
        conn.close()

def get_reminders(user_id: int = None):
    """取得提醒列表"""
    conn = get_db_connection()
    if not conn:
        return []

    try:
        cursor = conn.cursor(dictionary=True)

        if user_id is not None:
            cursor.execute('SELECT id, channel_id, message, time, user_id, guild_id FROM reminders WHERE user_id = %s ORDER BY time', (user_id,))
        else:
            cursor.execute('SELECT id, channel_id, message, time, user_id, guild_id FROM reminders ORDER BY time')

        return cursor.fetchall()
    finally:
        conn.close()

def get_due_reminders(now: datetime):
    """取得到期的提醒"""
    conn = get_db_connection()
    if not conn:
        return []

    try:
        # 將帶時區的 datetime 轉換為 naive datetime，避免時區比對問題
        now_naive = now.replace(tzinfo=None)

        cursor = conn.cursor(dictionary=True)
        cursor.execute('SELECT id, channel_id, message, time, user_id, guild_id FROM reminders WHERE time <= %s', (now_naive,))
        return cursor.fetchall()
    finally:
        conn.close()

def delete_reminder(reminder_id: int):
    """刪除提醒"""
    conn = get_db_connection()
    if not conn:
        return False

    try:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM reminders WHERE id = %s', (reminder_id,))
        conn.commit()
        return True
    finally:
        conn.close()

def delete_reminder_by_user(user_id: int, index: int):
    """根據用戶和索引刪除提醒"""
    conn = get_db_connection()
    if not conn:
        return False

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute('SELECT id FROM reminders WHERE user_id = %s ORDER BY time', (user_id,))
        rows = cursor.fetchall()

        if 1 <= index <= len(rows):
            reminder_id = rows[index - 1]['id']
            cursor.execute('DELETE FROM reminders WHERE id = %s', (reminder_id,))
            conn.commit()
            return True
        return False
    finally:
        conn.close()

def add_daily_reminder(channel_id: int, message: str, reminder_time: str, user_id: int, guild_id: int):
    """新增每日提醒"""
    conn = get_db_connection()
    if not conn:
        return False

    try:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO daily_reminders (channel_id, message, time, user_id, guild_id, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (channel_id, message, reminder_time, user_id, guild_id, datetime.now(TZ).replace(tzinfo=None)))
        conn.commit()
        return True
    finally:
        conn.close()

def get_daily_reminders(user_id: int = None, time_filter: str = None):
    """取得每日提醒列表"""
    conn = get_db_connection()
    if not conn:
        return []

    try:
        cursor = conn.cursor(dictionary=True)

        query = 'SELECT id, channel_id, message, time, user_id, guild_id FROM daily_reminders'
        params = []
        conditions = []

        if user_id is not None:
            conditions.append('user_id = %s')
            params.append(user_id)
        if time_filter is not None:
            conditions.append('time = %s')
            params.append(time_filter)

        if conditions:
            query += ' WHERE ' + ' AND '.join(conditions)

        query += ' ORDER BY time'
        cursor.execute(query, tuple(params))
        return cursor.fetchall()
    finally:
        conn.close()

def delete_daily_reminder_by_user(user_id: int, index: int):
    """根據用戶和索引刪除每日提醒"""
    conn = get_db_connection()
    if not conn:
        return False

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute('SELECT id FROM daily_reminders WHERE user_id = %s ORDER BY time', (user_id,))
        rows = cursor.fetchall()

        if 1 <= index <= len(rows):
            reminder_id = rows[index - 1]['id']
            cursor.execute('DELETE FROM daily_reminders WHERE id = %s', (reminder_id,))
            conn.commit()
            return True
        return False
    finally:
        conn.close()

class ReminderBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()

    async def on_ready(self):
        print(f'已登入: {self.user}')
        print(f'當前時間 (台灣): {datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")}')
        reminders = await asyncio.to_thread(get_reminders)
        dailies = await asyncio.to_thread(get_daily_reminders)
        print(f'一次性提醒: {len(reminders)} 個')
        print(f'每日提醒: {len(dailies)} 個')
        self.loop.create_task(check_reminders())

bot = ReminderBot()

def parse_time(time_str: str) -> Optional[datetime]:
    time_str = time_str.strip()

    relative_pattern = r'^(\d+)(s|m|h|d)$'
    match = re.match(relative_pattern, time_str.lower())
    if match:
        value = int(match.group(1))
        unit = match.group(2)

        now = datetime.now(TZ)
        if unit == 's':
            return now + timedelta(seconds=value)
        elif unit == 'm':
            return now + timedelta(minutes=value)
        elif unit == 'h':
            return now + timedelta(hours=value)
        elif unit == 'd':
            return now + timedelta(days=value)

    try:
        dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M')
        return dt.replace(tzinfo=TZ)
    except ValueError:
        pass

    try:
        time_part = datetime.strptime(time_str, '%H:%M').time()
        now = datetime.now(TZ)
        reminder_time = datetime.combine(now.date(), time_part, tzinfo=TZ)
        if reminder_time < now:
            reminder_time += timedelta(days=1)
        return reminder_time
    except ValueError:
        pass

    return None

@bot.tree.command(name="remind", description="設置一次性提醒")
@app_commands.describe(
    message="要提醒的內容（可使用 @提及 用戶或角色）",
    time="提醒時間（例如：10m, 2h, 1d, 15:30, 2024-03-16 15:30）"
)
async def remind(interaction: discord.Interaction, message: str, time: str):
    """設置提醒命令"""
    reminder_time = parse_time(time)

    if reminder_time is None:
        await interaction.response.send_message(
            "❌ 無法解析時間格式！\n"
            "支援格式：`5s`, `10m`, `2h`, `1d`, `15:30`, `2024-03-16 15:30`",
            ephemeral=True
        )
        return

    if reminder_time < datetime.now(TZ):
        await interaction.response.send_message(
            "❌ 提醒時間不能是過去的時間！",
            ephemeral=True
        )
        return

    success = await asyncio.to_thread(
        add_reminder,
        channel_id=interaction.channel_id,
        message=message,
        reminder_time=reminder_time,
        user_id=interaction.user.id,
        guild_id=interaction.guild_id
    )
    if success:
        time_display = reminder_time.strftime('%Y-%m-%d %H:%M:%S')
        await interaction.response.send_message(
            f"✅ 已設置提醒！\n"
            f"📝 內容：{message}\n"
            f"⏰ 時間：{time_display}",
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            "❌ 設置提醒失敗，請稍後再試",
            ephemeral=True
        )

@bot.tree.command(name="daily", description="設置每天定時提醒")
@app_commands.describe(
    message="要提醒的內容（可使用 @提及 用戶或角色）",
    time="每天提醒的時間（格式：HH:MM，例如：09:00）"
)
async def daily_remind(interaction: discord.Interaction, message: str, time: str):
    """設置每日提醒命令"""
    try:
        parsed_time = datetime.strptime(time, '%H:%M')
        formatted_time = parsed_time.strftime('%H:%M')
    except ValueError:
        await interaction.response.send_message(
            "❌ 無法解析時間格式！請使用 `HH:MM` 格式，例如：`09:00`",
            ephemeral=True
        )
        return

    success = await asyncio.to_thread(
        add_daily_reminder,
        channel_id=interaction.channel_id,
        message=message,
        reminder_time=formatted_time,
        user_id=interaction.user.id,
        guild_id=interaction.guild_id
    )
    if success:
        await interaction.response.send_message(
            f"✅ 已設置每日提醒！\n"
            f"📝 內容：{message}\n"
            f"⏰ 每天時間：{formatted_time}",
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            "❌ 設置每日提醒失敗，請稍後再試",
            ephemeral=True
        )

@bot.tree.command(name="reminders", description="查看所有待處理的提醒")
async def list_reminders(interaction: discord.Interaction):
    """列出所有提醒"""
    user_reminders = await asyncio.to_thread(get_reminders, interaction.user.id)
    user_dailies = await asyncio.to_thread(get_daily_reminders, interaction.user.id)

    if not user_reminders and not user_dailies:
        await interaction.response.send_message("📭 你沒有待處理的提醒。", ephemeral=True)
        return

    embed = discord.Embed(title="📋 你的提醒列表", color=discord.Color.blue())

    if user_reminders:
        for i, reminder in enumerate(user_reminders, 1):
            time_str = reminder['time'].strftime('%Y-%m-%d %H:%M:%S')
            message_preview = reminder['message'][:40] + "..." if len(reminder['message']) > 40 else reminder['message']
            embed.add_field(name=f"🔔 一次性 #{i}", value=f"⏰ {time_str}\n📝 {message_preview}", inline=False)

    if user_dailies:
        for i, daily in enumerate(user_dailies, 1):
            message_preview = daily['message'][:40] + "..." if len(daily['message']) > 40 else daily['message']
            embed.add_field(name=f"📆 每日 #{i}", value=f"⏰ 每天 {daily['time']}\n📝 {message_preview}", inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="cancel", description="取消一次性提醒")
@app_commands.describe(index="要取消的提醒編號（使用 /reminders 查看）")
async def cancel_reminder(interaction: discord.Interaction, index: int):
    """取消提醒"""
    user_reminders = await asyncio.to_thread(get_reminders, interaction.user.id)

    if index < 1 or index > len(user_reminders):
        await interaction.response.send_message("❌ 無效的提醒編號！", ephemeral=True)
        return

    removed = user_reminders[index - 1]
    await asyncio.to_thread(delete_reminder, removed['id'])

    await interaction.response.send_message(
        f"✅ 已取消提醒：{removed['message'][:50]}",
        ephemeral=True
    )

@bot.tree.command(name="canceldaily", description="取消每日提醒")
@app_commands.describe(index="要取消的每日提醒編號（使用 /reminders 查看）")
async def cancel_daily(interaction: discord.Interaction, index: int):
    """取消每日提醒"""
    user_dailies = await asyncio.to_thread(get_daily_reminders, interaction.user.id)

    if index < 1 or index > len(user_dailies):
        await interaction.response.send_message("❌ 無效的每日提醒編號！", ephemeral=True)
        return

    removed = user_dailies[index - 1]
    await asyncio.to_thread(delete_daily_reminder_by_user, interaction.user.id, index)

    await interaction.response.send_message(
        f"✅ 已取消每日提醒：{removed['message'][:50]}",
        ephemeral=True
    )

async def check_reminders():
    """背景任務：檢查並發送提醒"""
    await bot.wait_until_ready()
    last_daily_check = {}

    while not bot.is_closed():
        try:
            now = datetime.now(TZ)

            # === 檢查一次性提醒 ===
            due_reminders = await asyncio.to_thread(get_due_reminders, now)

            for reminder in due_reminders:
                try:
                    channel = bot.get_channel(reminder['channel_id'])
                    if channel is None:
                        channel = await bot.fetch_channel(reminder['channel_id'])

                    await channel.send(reminder['message'])
                    print(f"[提醒已發送] {reminder['time']} - {reminder['message']}")

                    # 只有送成功才刪除
                    await asyncio.to_thread(delete_reminder, reminder['id'])

                except Exception as e:
                    print(f"[提醒發送失敗，保留資料稍後重試] reminder_id={reminder['id']}, error={e}")

            # === 檢查每日提醒 ===
            current_time_str = now.strftime('%H:%M')
            daily_reminders = await asyncio.to_thread(get_daily_reminders, None, current_time_str)

            for daily in daily_reminders:
                check_key = f"{daily['id']}_{now.strftime('%Y-%m-%d')}"

                if check_key not in last_daily_check:
                    try:
                        channel = bot.get_channel(daily['channel_id'])
                        if channel is None:
                            channel = await bot.fetch_channel(daily['channel_id'])

                        await channel.send(daily['message'])
                        print(f"[每日提醒已發送] {daily['time']} - {daily['message']}")
                        last_daily_check[check_key] = True

                    except Exception as e:
                        print(f"[每日提醒發送失敗] daily_id={daily['id']}, error={e}")

            # 清理舊紀錄
            today_str = now.strftime('%Y-%m-%d')
            keys_to_remove = [k for k in last_daily_check if today_str not in k]
            for k in keys_to_remove:
                del last_daily_check[k]

        except Exception as e:
            print(f"[背景任務發生錯誤] {e}")

        await asyncio.sleep(5)

def main():
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        print("❌ 請在 .env 文件中設置 DISCORD_TOKEN")
        return

    if not all([MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE]):
        print("❌ 請在 .env 文件中設置 MySQL 連線資訊")
        print("   MYSQL_HOST, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE")
        return

    if not init_db():
        print("❌ 資料庫初始化失敗")
        return
    print('✅ 資料庫連線成功')
    bot.run(token)

if __name__ == "__main__":
    main()
