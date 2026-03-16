import os
import asyncio
import sqlite3
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()

# 使用台灣時區
TZ = ZoneInfo("Asia/Taipei")

# 資料庫路徑
DB_FILE = "reminders.db"

def init_db():
    """初始化資料庫"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # 一次性提醒表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            time TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            guild_id INTEGER
        )
    ''')

    # 每日提醒表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            time TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            guild_id INTEGER,
            created_at TEXT
        )
    ''')

    conn.commit()
    conn.close()

def add_reminder(channel_id: int, message: str, time: datetime, user_id: int, guild_id: int):
    """新增一次性提醒"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO reminders (channel_id, message, time, user_id, guild_id)
        VALUES (?, ?, ?, ?, ?)
    ''', (channel_id, message, time.isoformat(), user_id, guild_id))
    conn.commit()
    conn.close()

def get_reminders(user_id: int = None):
    """取得提醒列表"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    if user_id:
        cursor.execute('SELECT id, channel_id, message, time, user_id, guild_id FROM reminders WHERE user_id = ?', (user_id,))
    else:
        cursor.execute('SELECT id, channel_id, message, time, user_id, guild_id FROM reminders')

    rows = cursor.fetchall()
    conn.close()

    reminders = []
    for row in rows:
        reminders.append({
            'id': row[0],
            'channel_id': row[1],
            'message': row[2],
            'time': datetime.fromisoformat(row[3]),
            'user_id': row[4],
            'guild_id': row[5]
        })
    return reminders

def get_due_reminders(now: datetime):
    """取得到期的提醒"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT id, channel_id, message, time, user_id, guild_id FROM reminders WHERE time <= ?', (now.isoformat(),))
    rows = cursor.fetchall()
    conn.close()

    reminders = []
    for row in rows:
        reminders.append({
            'id': row[0],
            'channel_id': row[1],
            'message': row[2],
            'time': datetime.fromisoformat(row[3]),
            'user_id': row[4],
            'guild_id': row[5]
        })
    return reminders

def delete_reminder(reminder_id: int):
    """刪除提醒"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM reminders WHERE id = ?', (reminder_id,))
    conn.commit()
    conn.close()

def delete_reminder_by_user(user_id: int, index: int):
    """根據用戶和索引刪除提醒"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM reminders WHERE user_id = ? ORDER BY time', (user_id,))
    rows = cursor.fetchall()

    if 1 <= index <= len(rows):
        reminder_id = rows[index - 1][0]
        cursor.execute('DELETE FROM reminders WHERE id = ?', (reminder_id,))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False

def add_daily_reminder(channel_id: int, message: str, time: str, user_id: int, guild_id: int):
    """新增每日提醒"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO daily_reminders (channel_id, message, time, user_id, guild_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (channel_id, message, time, user_id, guild_id, datetime.now(TZ).isoformat()))
    conn.commit()
    conn.close()

def get_daily_reminders(user_id: int = None):
    """取得每日提醒列表"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    if user_id:
        cursor.execute('SELECT id, channel_id, message, time, user_id, guild_id FROM daily_reminders WHERE user_id = ?', (user_id,))
    else:
        cursor.execute('SELECT id, channel_id, message, time, user_id, guild_id FROM daily_reminders')

    rows = cursor.fetchall()
    conn.close()

    dailies = []
    for row in rows:
        dailies.append({
            'id': row[0],
            'channel_id': row[1],
            'message': row[2],
            'time': row[3],
            'user_id': row[4],
            'guild_id': row[5]
        })
    return dailies

def delete_daily_reminder_by_user(user_id: int, index: int):
    """根據用戶和索引刪除每日提醒"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM daily_reminders WHERE user_id = ? ORDER BY time', (user_id,))
    rows = cursor.fetchall()

    if 1 <= index <= len(rows):
        reminder_id = rows[index - 1][0]
        cursor.execute('DELETE FROM daily_reminders WHERE id = ?', (reminder_id,))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False

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
        init_db()
        print(f'一次性提醒: {len(get_reminders())} 個')
        print(f'每日提醒: {len(get_daily_reminders())} 個')
        self.loop.create_task(check_reminders())

bot = ReminderBot()

def parse_time(time_str: str) -> Optional[datetime]:
    """
    解析時間字串，支援格式：
    - 5s, 10m, 2h, 1d (秒/分/時/天)
    - 2024-03-16 15:30 (指定日期時間)
    - 15:30 (今天指定時間)
    """
    time_str = time_str.strip()

    # 相對時間格式 (5s, 10m, 2h, 1d)
    relative_pattern = r'^(\d+)(s|m|h|d)$'
    match = re.match(relative_pattern, time_str.lower())
    if match:
        value = int(match.group(1))
        unit = match.group(2)

        if unit == 's':
            return datetime.now(TZ) + timedelta(seconds=value)
        elif unit == 'm':
            return datetime.now(TZ) + timedelta(minutes=value)
        elif unit == 'h':
            return datetime.now(TZ) + timedelta(hours=value)
        elif unit == 'd':
            return datetime.now(TZ) + timedelta(days=value)

    # 完整日期時間格式 (2024-03-16 15:30)
    try:
        return datetime.strptime(time_str, '%Y-%m-%d %H:%M')
    except ValueError:
        pass

    # 只有時間格式 (15:30)
    try:
        time_part = datetime.strptime(time_str, '%H:%M').time()
        reminder_time = datetime.combine(datetime.now(TZ).date(), time_part, tzinfo=TZ)
        if reminder_time < datetime.now(TZ):
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

    add_reminder(
        channel_id=interaction.channel_id,
        message=message,
        time=reminder_time,
        user_id=interaction.user.id,
        guild_id=interaction.guild_id
    )

    time_display = reminder_time.strftime('%Y-%m-%d %H:%M:%S')

    await interaction.response.send_message(
        f"✅ 已設置提醒！\n"
        f"📝 內容：{message}\n"
        f"⏰ 時間：{time_display}",
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
        datetime.strptime(time, '%H:%M')
    except ValueError:
        await interaction.response.send_message(
            "❌ 無法解析時間格式！請使用 `HH:MM` 格式，例如：`09:00`",
            ephemeral=True
        )
        return

    add_daily_reminder(
        channel_id=interaction.channel_id,
        message=message,
        time=time,
        user_id=interaction.user.id,
        guild_id=interaction.guild_id
    )

    await interaction.response.send_message(
        f"✅ 已設置每日提醒！\n"
        f"📝 內容：{message}\n"
        f"⏰ 每天時間：{time}",
        ephemeral=True
    )

@bot.tree.command(name="reminders", description="查看所有待處理的提醒")
async def list_reminders(interaction: discord.Interaction):
    """列出所有提醒"""
    user_reminders = get_reminders(interaction.user.id)
    user_dailies = get_daily_reminders(interaction.user.id)

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
    user_reminders = get_reminders(interaction.user.id)

    if index < 1 or index > len(user_reminders):
        await interaction.response.send_message("❌ 無效的提醒編號！", ephemeral=True)
        return

    removed = user_reminders[index - 1]
    delete_reminder(removed['id'])

    await interaction.response.send_message(
        f"✅ 已取消提醒：{removed['message'][:50]}",
        ephemeral=True
    )

@bot.tree.command(name="canceldaily", description="取消每日提醒")
@app_commands.describe(index="要取消的每日提醒編號（使用 /reminders 查看）")
async def cancel_daily(interaction: discord.Interaction, index: int):
    """取消每日提醒"""
    user_dailies = get_daily_reminders(interaction.user.id)

    if index < 1 or index > len(user_dailies):
        await interaction.response.send_message("❌ 無效的每日提醒編號！", ephemeral=True)
        return

    removed = user_dailies[index - 1]
    delete_daily_reminder_by_user(interaction.user.id, index)

    await interaction.response.send_message(
        f"✅ 已取消每日提醒：{removed['message'][:50]}",
        ephemeral=True
    )

async def check_reminders():
    """背景任務：檢查並發送提醒"""
    await bot.wait_until_ready()
    last_daily_check = {}

    while not bot.is_closed():
        now = datetime.now(TZ)

        # === 檢查一次性提醒 ===
        due_reminders = get_due_reminders(now)

        for reminder in due_reminders:
            try:
                channel = bot.get_channel(reminder['channel_id'])
                if channel:
                    await channel.send(reminder['message'])
                    print(f"[提醒已發送] {reminder['time']} - {reminder['message']}")
                else:
                    print(f"[錯誤] 無法獲取頻道 ID: {reminder['channel_id']}")
            except Exception as e:
                print(f"發送提醒時出錯: {e}")

            delete_reminder(reminder['id'])

        # === 檢查每日提醒 ===
        current_time_str = now.strftime('%H:%M')
        daily_reminders = get_daily_reminders()

        for daily in daily_reminders:
            if daily['time'] == current_time_str:
                check_key = f"{daily['channel_id']}_{daily['time']}_{now.strftime('%Y-%m-%d')}"

                if check_key not in last_daily_check:
                    last_daily_check[check_key] = True

                    try:
                        channel = bot.get_channel(daily['channel_id'])
                        if channel:
                            await channel.send(daily['message'])
                            print(f"[每日提醒已發送] {daily['time']} - {daily['message']}")
                        else:
                            print(f"[錯誤] 無法獲取頻道 ID: {daily['channel_id']}")
                    except Exception as e:
                        print(f"發送每日提醒時出錯: {e}")

        # 清理過期的 last_daily_check
        today_str = now.strftime('%Y-%m-%d')
        keys_to_remove = [k for k in last_daily_check if today_str not in k]
        for k in keys_to_remove:
            del last_daily_check[k]

        await asyncio.sleep(1)

def main():
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        print("❌ 請在 .env 文件中設置 DISCORD_TOKEN")
        return

    init_db()
    bot.run(token)

if __name__ == "__main__":
    main()
