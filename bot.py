import os
import asyncio
import re
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from typing import Optional
import mysql.connector
from mysql.connector import Error
from mysql.connector import pooling
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

MYSQL_POOL_SIZE = int(os.getenv('MYSQL_POOL_SIZE', 5))

db_pool = None

def init_db_pool():
    global db_pool
    try:
        db_pool = mysql.connector.pooling.MySQLConnectionPool(
            pool_name="mypool",
            pool_size=MYSQL_POOL_SIZE,
            pool_reset_session=True,
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DATABASE,
            charset='utf8mb4'
        )
        return True
    except Error as e:
        print(f"初始化連線池錯誤: {e}")
        return False

def get_db_connection():
    """取得資料庫連線"""
    global db_pool
    if db_pool is None:
        if not init_db_pool():
            return None
    try:
        return db_pool.get_connection()
    except Error as e:
        print(f"取得資料庫連線錯誤: {e}")
        return None

def init_db():
    """初始化資料庫"""
    conn = get_db_connection()
    if not conn:
        return False

    cursor = None
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
                created_at DATETIME,
                last_triggered_date DATE
            )
        ''')

        # 嘗試新增 last_triggered_date 欄位 (相容舊版本)
        cursor.execute('''
            SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'daily_reminders' AND COLUMN_NAME = 'last_triggered_date'
        ''', (MYSQL_DATABASE,))
        if cursor.fetchone()[0] == 0:
            cursor.execute("ALTER TABLE daily_reminders ADD COLUMN last_triggered_date DATE")

        conn.commit()
        return True
    finally:
        if cursor:
            cursor.close()
        conn.close()

def add_reminder(channel_id: int, message: str, reminder_time: datetime, user_id: int, guild_id: int):
    """新增一次性提醒"""
    conn = get_db_connection()
    if not conn:
        print("[add_reminder] 無法取得資料庫連線")
        return False

    cursor = None
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
        if cursor:
            cursor.close()
        conn.close()

def get_reminders(user_id: int = None):
    """取得提醒列表"""
    conn = get_db_connection()
    if not conn:
        return []

    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)

        if user_id is not None:
            cursor.execute('SELECT id, channel_id, message, time, user_id, guild_id FROM reminders WHERE user_id = %s ORDER BY time', (user_id,))
        else:
            cursor.execute('SELECT id, channel_id, message, time, user_id, guild_id FROM reminders ORDER BY time')

        return cursor.fetchall()
    finally:
        if cursor:
            cursor.close()
        conn.close()

def get_due_reminders(now: datetime):
    """取得到期的提醒"""
    conn = get_db_connection()
    if not conn:
        return []

    cursor = None
    try:
        # 將帶時區的 datetime 轉換為 naive datetime，避免時區比對問題
        now_naive = now.replace(tzinfo=None)

        cursor = conn.cursor(dictionary=True)
        cursor.execute('SELECT id, channel_id, message, time, user_id, guild_id FROM reminders WHERE time <= %s', (now_naive,))
        return cursor.fetchall()
    finally:
        if cursor:
            cursor.close()
        conn.close()

def delete_reminder(reminder_id: int):
    """刪除提醒"""
    conn = get_db_connection()
    if not conn:
        return False

    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM reminders WHERE id = %s', (reminder_id,))
        conn.commit()
        return True
    finally:
        if cursor:
            cursor.close()
        conn.close()

def delete_reminder_by_user(user_id: int, index: int):
    """根據用戶和索引刪除提醒"""
    conn = get_db_connection()
    if not conn:
        return False

    cursor = None
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
        if cursor:
            cursor.close()
        conn.close()

def add_daily_reminder(channel_id: int, message: str, reminder_time: str, user_id: int, guild_id: int):
    """新增每日提醒"""
    conn = get_db_connection()
    if not conn:
        print("[add_daily_reminder] 無法取得資料庫連線")
        return False

    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO daily_reminders (channel_id, message, time, user_id, guild_id, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (channel_id, message, reminder_time, user_id, guild_id, datetime.now(TZ).replace(tzinfo=None)))
        conn.commit()
        return True
    finally:
        if cursor:
            cursor.close()
        conn.close()

def get_daily_reminders(user_id: int = None, time_filter: str = None, date_filter: date = None):
    """取得每日提醒列表"""
    conn = get_db_connection()
    if not conn:
        return []

    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)

        query = 'SELECT id, channel_id, message, time, user_id, guild_id, last_triggered_date FROM daily_reminders'
        params = []
        conditions = []

        if user_id is not None:
            conditions.append('user_id = %s')
            params.append(user_id)
        if time_filter is not None:
            conditions.append('time <= %s')
            params.append(time_filter)
        if date_filter is not None:
            conditions.append('(last_triggered_date < %s OR last_triggered_date IS NULL)')
            params.append(date_filter)

        if conditions:
            query += ' WHERE ' + ' AND '.join(conditions)

        query += ' ORDER BY time'
        cursor.execute(query, tuple(params))
        return cursor.fetchall()
    finally:
        if cursor:
            cursor.close()
        conn.close()

def delete_daily_reminder(reminder_id: int):
    """刪除每日提醒"""
    conn = get_db_connection()
    if not conn:
        return False

    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM daily_reminders WHERE id = %s', (reminder_id,))
        conn.commit()
        return True
    finally:
        if cursor:
            cursor.close()
        conn.close()

def delete_daily_reminder_by_user(user_id: int, index: int):
    """根據用戶和索引刪除每日提醒"""
    conn = get_db_connection()
    if not conn:
        return False

    cursor = None
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
        if cursor:
            cursor.close()
        conn.close()

def update_daily_last_triggered(reminder_id: int, triggered_date: date):
    """更新每日提醒最後觸發日期"""
    conn = get_db_connection()
    if not conn:
        return False

    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute('UPDATE daily_reminders SET last_triggered_date = %s WHERE id = %s', (triggered_date, reminder_id))
        conn.commit()
        return True
    finally:
        if cursor:
            cursor.close()
        conn.close()

class ReminderBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        # 建議有需要時手動同步，避免被 Discord API Rate Limit 阻擋
        # await self.tree.sync()
        pass

    async def on_ready(self):
        print(f'已登入: {self.user}')
        print(f'當前時間 (台灣): {datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")}')
        reminders = await asyncio.to_thread(get_reminders)
        dailies = await asyncio.to_thread(get_daily_reminders)
        print(f'一次性提醒: {len(reminders)} 個')
        print(f'每日提醒: {len(dailies)} 個')
        self.loop.create_task(check_reminders())

bot = ReminderBot()

@bot.command()
@commands.is_owner()
async def sync(ctx):
    """手動同步 Slash 指令 (限機器人擁有者)"""
    await bot.tree.sync()
    await ctx.send("✅ Slash 指令已全域同步！")

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
    await interaction.response.defer(ephemeral=True)
    reminder_time = parse_time(time)

    if reminder_time is None:
        await interaction.followup.send("❌ 無法解析時間格式！\n支援格式：`5s`, `10m`, `2h`, `1d`, `15:30`, `2024-03-16 15:30`")
        return

    if reminder_time < datetime.now(TZ):
        await interaction.followup.send("❌ 提醒時間不能是過去的時間！")
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
        await interaction.followup.send(
            f"✅ 已設置提醒！\n"
            f"📝 內容：{message}\n"
            f"⏰ 時間：{time_display}"
        )
    else:
        await interaction.followup.send("❌ 設置提醒失敗，請稍後再試")

@bot.tree.command(name="daily", description="設置每天定時提醒")
@app_commands.describe(
    message="要提醒的內容（可使用 @提及 用戶或角色）",
    time="每天提醒的時間（格式：HH:MM，例如：09:00）"
)
async def daily_remind(interaction: discord.Interaction, message: str, time: str):
    """設置每日提醒命令"""
    await interaction.response.defer(ephemeral=True)
    try:
        parsed_time = datetime.strptime(time, '%H:%M')
        formatted_time = parsed_time.strftime('%H:%M')
    except ValueError:
        await interaction.followup.send("❌ 無法解析時間格式！請使用 `HH:MM` 格式，例如：`09:00`")
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
        await interaction.followup.send(
            f"✅ 已設置每日提醒！\n"
            f"📝 內容：{message}\n"
            f"⏰ 每天時間：{formatted_time}"
        )
    else:
        await interaction.followup.send("❌ 設置每日提醒失敗，請稍後再試")

@bot.tree.command(name="reminders", description="查看所有待處理的提醒")
async def list_reminders(interaction: discord.Interaction):
    """列出所有提醒"""
    await interaction.response.defer(ephemeral=True)
    user_reminders = await asyncio.to_thread(get_reminders, interaction.user.id)
    user_dailies = await asyncio.to_thread(get_daily_reminders, interaction.user.id)

    if not user_reminders and not user_dailies:
        await interaction.followup.send("📭 你沒有待處理的提醒。")
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

    await interaction.followup.send(embed=embed)

@bot.tree.command(name="cancel", description="取消一次性提醒")
@app_commands.describe(index="要取消的提醒編號（使用 /reminders 查看）")
async def cancel_reminder(interaction: discord.Interaction, index: int):
    """取消提醒"""
    await interaction.response.defer(ephemeral=True)
    user_reminders = await asyncio.to_thread(get_reminders, interaction.user.id)

    if index < 1 or index > len(user_reminders):
        await interaction.followup.send("❌ 無效的提醒編號！")
        return

    removed = user_reminders[index - 1]
    await asyncio.to_thread(delete_reminder, removed['id'])

    await interaction.followup.send(f"✅ 已取消提醒：{removed['message'][:50]}")

@bot.tree.command(name="canceldaily", description="取消每日提醒")
@app_commands.describe(index="要取消的每日提醒編號（使用 /reminders 查看）")
async def cancel_daily(interaction: discord.Interaction, index: int):
    """取消每日提醒"""
    await interaction.response.defer(ephemeral=True)
    user_dailies = await asyncio.to_thread(get_daily_reminders, interaction.user.id)

    if index < 1 or index > len(user_dailies):
        await interaction.followup.send("❌ 無效的每日提醒編號！")
        return

    removed = user_dailies[index - 1]
    await asyncio.to_thread(delete_daily_reminder, removed['id'])

    await interaction.followup.send(f"✅ 已取消每日提醒：{removed['message'][:50]}")

async def check_reminders():
    """背景任務：檢查並發送提醒"""
    await bot.wait_until_ready()

    consecutive_errors = 0

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

                except (discord.Forbidden, discord.NotFound) as e:
                    print(f"[{'權限不足' if isinstance(e, discord.Forbidden) else '找不到頻道'}] 刪除提醒: {reminder['id']}")
                    await asyncio.to_thread(delete_reminder, reminder['id'])
                except Exception as e:
                    print(f"[提醒發送失敗，保留資料稍後重試] reminder_id={reminder['id']}, error={e}")

            # === 檢查每日提醒 ===
            # 使用 <= 比對搭配日期過濾，確保補發邏輯且不重複抓取
            current_time_str = now.strftime('%H:%M')
            today_date = now.date()
            daily_reminders = await asyncio.to_thread(get_daily_reminders, None, current_time_str, today_date)

            for daily in daily_reminders:
                try:
                    channel = bot.get_channel(daily['channel_id'])
                    if channel is None:
                        channel = await bot.fetch_channel(daily['channel_id'])

                    await channel.send(daily['message'])
                    print(f"[每日提醒已發送] {daily['time']} - {daily['message']}")

                    # 更新最後觸發日期為今天
                    await asyncio.to_thread(update_daily_last_triggered, daily['id'], today_date)

                except (discord.Forbidden, discord.NotFound) as e:
                    print(f"[{'權限不足' if isinstance(e, discord.Forbidden) else '找不到頻道'}] 刪除每日提醒: {daily['id']}")
                    await asyncio.to_thread(delete_daily_reminder, daily['id'])
                except Exception as e:
                    print(f"[每日提醒發送失敗] daily_id={daily['id']}, error={e}")

            consecutive_errors = 0

        except Exception as e:
            consecutive_errors += 1
            backoff = min(5 * (2 ** consecutive_errors), 300)
            print(f"[背景任務發生錯誤] (連續第 {consecutive_errors} 次) {e}, {backoff} 秒後重試")
            await asyncio.sleep(backoff)
            continue

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
