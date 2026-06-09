import sys
import os
import discord
from discord.ext import commands
from discord import app_commands
from pymongo import MongoClient
import certifi
from datetime import datetime, timedelta

if len(sys.argv) < 3:
    print("Usage: python discord_bot_runner.py <BOT_TOKEN> <RESELLER_ID>")
    sys.exit(1)

DISCORD_TOKEN = sys.argv[1]
RESELLER_ID = sys.argv[2]
MONGO_URI = os.getenv('MONGO_URI')

if not MONGO_URI:
    print("FATAL: MONGO_URI environment variable is missing.")
    sys.exit(1)

client = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
db = client.get_database()
uids_col = db['uids']
users_col = db['users']

class StealthBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=discord.Intents.default())

    async def setup_hook(self):
        print("Syncing slash commands...")
        await self.tree.sync()
        print("Slash commands synced successfully.")

bot = StealthBot()

@bot.event
async def on_ready():
    print(f"[{RESELLER_ID}] Logged in as {bot.user.name} ({bot.user.id})")
    print(f"[{RESELLER_ID}] Bot is online and connected to MongoDB.")

@bot.tree.command(name="check_uid", description="Check the status of a specific UID")
@app_commands.describe(uid="The UID to check")
async def check_uid(interaction: discord.Interaction, uid: str):
    record = uids_col.find_one({"uid": uid, "reseller_id": RESELLER_ID})
    if not record:
        await interaction.response.send_message(f"❌ UID `{uid}` is not registered under your reseller account.", ephemeral=True)
        return

    exp_date_str = record.get('exp_date', 'Never')
    status_msg = f"✅ **UID Found:** `{uid}`\n"
    status_msg += f"**Key:** `{record.get('key', 'N/A')}`\n"
    status_msg += f"**Expires:** {exp_date_str}"
    
    await interaction.response.send_message(status_msg, ephemeral=True)

@bot.tree.command(name="add_uid", description="Add a new UID to your reseller database")
@app_commands.describe(uid="The UID to whitelist", days="Number of days (0 for lifetime)")
async def add_uid(interaction: discord.Interaction, uid: str, days: int):
    # Check if the discord user is authorized (simplification for this example)
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
        return

    # Check limits for reseller
    reseller = users_col.find_one({"username": RESELLER_ID})
    if not reseller:
        await interaction.response.send_message("❌ Reseller account not found in DB.", ephemeral=True)
        return

    limit = int(reseller.get('reseller_limit', 0))
    current_count = uids_col.count_documents({"reseller_id": RESELLER_ID})

    if current_count >= limit and limit != -1:
        await interaction.response.send_message(f"⚠️ You have reached your active UID limit ({limit}). Please purge expired slots or upgrade.", ephemeral=True)
        return

    existing = uids_col.find_one({"uid": uid})
    if existing:
        await interaction.response.send_message(f"⚠️ UID `{uid}` is already in the global database.", ephemeral=True)
        return

    if days == 0:
        exp_date_str = "Lifetime"
    else:
        exp_date = datetime.now() + timedelta(days=days)
        exp_date_str = exp_date.strftime("%Y-%m-%d %H:%M:%S")

    new_record = {
        "uid": uid,
        "exp_date": exp_date_str,
        "reseller_id": RESELLER_ID,
        "key": f"BOT-{RESELLER_ID.upper()}",
        "hwid": ""
    }
    
    uids_col.insert_one(new_record)
    await interaction.response.send_message(f"✅ UID `{uid}` has been successfully whitelisted for {days if days > 0 else 'Lifetime'} days.", ephemeral=True)

bot.run(DISCORD_TOKEN)
