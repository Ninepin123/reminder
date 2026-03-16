import os
import asyncio
import json
import re
from datetime import datetime, timedelta
from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()

# 儲存提醒任務
reminders = []
daily_reminders = []

# 持久化文件路徑
REMINDERS_FILE = "reminders.json"
DAILY_FILE = "daily_reminders.json"

def save_data():
    """儲存資料到文件"""
    data = {
        'reminders': [],
        'daily_reminders': daily_reminders
    }

    for r in reminders:
        data['reminders'].append({
            'channel_id': r['channel_id'],
            'message': r['message'],
            'time': r['time'].isoformat(),
            'user_id': r['user_id'],
            'guild_id': r['guild_id']
        })

    with open(REMINDERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_data():
    """從文件載入資料"""
    global reminders, daily_reminders

    try:
        with open(REMINDERS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 載入一次性提醒
        for r in data.get('reminders', []):
            r['time'] = datetime.fromisoformat(r['time'])
            # 只載入未過期的提醒
            if r['time'] > datetime.now():
                reminders.append(r)

        # 載入每日提醒
        daily_reminders = data.get('daily_reminders', [])

    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"載入資料時出錯: {e}")

class ReminderBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        # 註冊 slash command
        await self.tree.sync()

    async def on_ready(self):
        print(f'已登入: {self.user}')
        # 載入已儲存的提醒
        load_data()
        print(f'已載入 {len(reminders)} 個一次性提醒')
        print(f'已載入 {len(daily_reminders)} 個每日提醒')
        # 啟動提醒檢查任務
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
            return datetime.now() + timedelta(seconds=value)
        elif unit == 'm':
            return datetime.now() + timedelta(minutes=value)
        elif unit == 'h':
            return datetime.now() + timedelta(hours=value)
        elif unit == 'd':
            return datetime.now() + timedelta(days=value)

    # 完整日期時間格式 (2024-03-16 15:30)
    try:
        return datetime.strptime(time_str, '%Y-%m-%d %H:%M')
    except ValueError:
        pass

    # 只有時間格式 (15:30)
    try:
        time_part = datetime.strptime(time_str, '%H:%M').time()
        reminder_time = datetime.combine(datetime.now().date(), time_part)
        # 如果時間已過，設為明天
        if reminder_time < datetime.now():
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

    if reminder_time < datetime.now():
        await interaction.response.send_message(
            "❌ 提醒時間不能是過去的時間！",
            ephemeral=True
        )
        return

    # 儲存提醒
    reminder = {
        'channel_id': interaction.channel_id,
        'message': message,
        'time': reminder_time,
        'user_id': interaction.user.id,
        'guild_id': interaction.guild_id
    }
    reminders.append(reminder)
    save_data()

    # 格式化顯示時間
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
    # 驗證時間格式
    try:
        time_part = datetime.strptime(time, '%H:%M').time()
    except ValueError:
        await interaction.response.send_message(
            "❌ 無法解析時間格式！請使用 `HH:MM` 格式，例如：`09:00`",
            ephemeral=True
        )
        return

    # 儲存每日提醒
    daily = {
        'channel_id': interaction.channel_id,
        'message': message,
        'time': time,  # 存儲為字串 "HH:MM"
        'user_id': interaction.user.id,
        'guild_id': interaction.guild_id,
        'created_at': datetime.now().isoformat()
    }
    daily_reminders.append(daily)
    save_data()

    await interaction.response.send_message(
        f"✅ 已設置每日提醒！\n"
        f"📝 內容：{message}\n"
        f"⏰ 每天時間：{time}",
        ephemeral=True
    )

@bot.tree.command(name="reminders", description="查看所有待處理的提醒")
async def list_reminders(interaction: discord.Interaction):
    """列出所有提醒"""
    user_reminders = [r for r in reminders if r['user_id'] == interaction.user.id]
    user_dailies = [d for d in daily_reminders if d['user_id'] == interaction.user.id]

    if not user_reminders and not user_dailies:
        await interaction.response.send_message("📭 你沒有待處理的提醒。", ephemeral=True)
        return

    embed = discord.Embed(title="📋 你的提醒列表", color=discord.Color.blue())

    # 一次性提醒
    if user_reminders:
        for i, reminder in enumerate(user_reminders, 1):
            time_str = reminder['time'].strftime('%Y-%m-%d %H:%M:%S')
            message_preview = reminder['message'][:40] + "..." if len(reminder['message']) > 40 else reminder['message']
            embed.add_field(name=f"🔔 一次性 #{i}", value=f"⏰ {time_str}\n📝 {message_preview}", inline=False)

    # 每日提醒
    if user_dailies:
        for i, daily in enumerate(user_dailies, 1):
            message_preview = daily['message'][:40] + "..." if len(daily['message']) > 40 else daily['message']
            embed.add_field(name=f"📆 每日 #{i}", value=f"⏰ 每天 {daily['time']}\n📝 {message_preview}", inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="cancel", description="取消一次性提醒")
@app_commands.describe(index="要取消的提醒編號（使用 /reminders 查看）")
async def cancel_reminder(interaction: discord.Interaction, index: int):
    """取消提醒"""
    user_reminders = [(i, r) for i, r in enumerate(reminders) if r['user_id'] == interaction.user.id]

    if index < 1 or index > len(user_reminders):
        await interaction.response.send_message("❌ 無效的提醒編號！", ephemeral=True)
        return

    original_index = user_reminders[index - 1][0]
    removed = reminders.pop(original_index)
    save_data()

    await interaction.response.send_message(
        f"✅ 已取消提醒：{removed['message'][:50]}",
        ephemeral=True
    )

@bot.tree.command(name="canceldaily", description="取消每日提醒")
@app_commands.describe(index="要取消的每日提醒編號（使用 /reminders 查看）")
async def cancel_daily(interaction: discord.Interaction, index: int):
    """取消每日提醒"""
    user_dailies = [(i, d) for i, d in enumerate(daily_reminders) if d['user_id'] == interaction.user.id]

    if index < 1 or index > len(user_dailies):
        await interaction.response.send_message("❌ 無效的每日提醒編號！", ephemeral=True)
        return

    original_index = user_dailies[index - 1][0]
    removed = daily_reminders.pop(original_index)
    save_data()

    await interaction.response.send_message(
        f"✅ 已取消每日提醒：{removed['message'][:50]}",
        ephemeral=True
    )

async def check_reminders():
    """背景任務：檢查並發送提醒"""
    await bot.wait_until_ready()
    last_daily_check = {}

    while not bot.is_closed():
        now = datetime.now()

        # === 檢查一次性提醒 ===
        due_reminders = []
        for reminder in reminders:
            if reminder['time'] <= now:
                due_reminders.append(reminder)

        for reminder in due_reminders:
            try:
                channel = bot.get_channel(reminder['channel_id'])
                if channel:
                    content = reminder['message']
                    await channel.send(content)
            except Exception as e:
                print(f"發送提醒時出錯: {e}")

            reminders.remove(reminder)

        # === 檢查每日提醒 ===
        current_time_str = now.strftime('%H:%M')

        for daily in daily_reminders:
            if daily['time'] == current_time_str:
                # 使用 channel_id + time 作為 key，確保每個提醒每天只發一次
                check_key = f"{daily['channel_id']}_{daily['time']}_{now.strftime('%Y-%m-%d')}"

                if check_key not in last_daily_check:
                    last_daily_check[check_key] = True

                    try:
                        channel = bot.get_channel(daily['channel_id'])
                        if channel:
                            content = daily['message']
                            await channel.send(content)
                    except Exception as e:
                        print(f"發送每日提醒時出錯: {e}")

        # 清理過期的 last_daily_check（保留最近3天的記錄）
        today_str = now.strftime('%Y-%m-%d')
        keys_to_remove = [k for k in last_daily_check if today_str not in k]
        for k in keys_to_remove:
            del last_daily_check[k]

        # 儲存資料
        if due_reminders:
            save_data()

        # 每1秒檢查一次（確保不會錯過每日提醒）
        await asyncio.sleep(1)

def main():
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        print("❌ 請在 .env 文件中設置 DISCORD_TOKEN")
        return

    bot.run(token)

if __name__ == "__main__":
    main()
