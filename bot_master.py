import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import os
import subprocess
import time
import threading
import psutil
import pyautogui
from datetime import datetime, timedelta

# Configuration
TOKEN = os.getenv('TG_TOKEN')
CHAT_ID = os.getenv('TG_CHATID') # Int conversion happens in logic
bot = telebot.TeleBot(TOKEN)

# State Management
state = {
    "crd_cmd": None,
    "pin": None,
    "duration": 0,
    "start_time": None,
    "active": False,
    "warned_30": False
}

def is_owner(message):
    # Ensure CHAT_ID is compared as string/int correctly
    return str(message.chat.id) == str(CHAT_ID)

# --- KEYBOARDS ---
def get_main_menu():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📸 Screenshot", callback_data="shot"),
        InlineKeyboardButton("📊 System Info", callback_data="info"),
        InlineKeyboardButton("⏳ Extend +30m", callback_data="extend"),
        InlineKeyboardButton("💀 Kill Session", callback_data="kill")
    )
    return markup

# --- HANDLERS ---

@bot.message_handler(commands=['start'], func=is_owner)
def send_welcome(message):
    bot.reply_to(message, "🤖 **TryGitRDP Online**\n\nWaiting for input...\nPLEASE PASTE THE **CRD POWERSHELL COMMAND** NOW.")

# 1. Catch CRD Command
@bot.message_handler(func=lambda msg: is_owner(msg) and state["crd_cmd"] is None)
def step_one_crd(message):
    if "remoting_start_host.exe" in message.text and "-code" in message.text:
        state["crd_cmd"] = message.text
        bot.reply_to(message, "✅ Command Received.\n\n👉 Now, enter your **6-DIGIT PIN**:")
    else:
        bot.reply_to(message, "❌ Invalid Command. Please copy the 'Windows (PowerShell)' command from Chrome Remote Desktop.")

# 2. Catch PIN
@bot.message_handler(func=lambda msg: is_owner(msg) and state["crd_cmd"] is not None and state["pin"] is None)
def step_two_pin(message):
    if message.text.isdigit() and len(message.text) >= 6:
        state["pin"] = message.text
        
        # Show Duration Options
        markup = InlineKeyboardMarkup(row_width=3)
        markup.add(
            InlineKeyboardButton("1 Hour", callback_data="time_60"),
            InlineKeyboardButton("3 Hours", callback_data="time_180"),
            InlineKeyboardButton("6 Hours", callback_data="time_350") # Max allowed slightly less than 360
        )
        bot.reply_to(message, "✅ PIN Saved.\n\n👉 Select **Session Duration**:", reply_markup=markup)
    else:
        bot.reply_to(message, "❌ PIN must be numbers only and at least 6 digits.")

# 3. Callback Handler (Buttons)
@bot.callback_query_handler(func=lambda call: str(call.message.chat.id) == str(CHAT_ID))
def callback_handler(call):
    # DURATION SELECTION
    if call.data.startswith("time_"):
        minutes = int(call.data.split("_")[1])
        state["duration"] = minutes
        state["start_time"] = datetime.now()
        state["active"] = True
        
        bot.edit_message_text(f"🚀 Starting RDP for {minutes} minutes...\nPlease wait.", 
                              call.message.chat.id, call.message.message_id)
        
        # Start RDP in a separate thread
        threading.Thread(target=start_rdp).start()

    # SCREENSHOT
    elif call.data == "shot":
        try:
            bot.answer_callback_query(call.id, "Capturing...")
            screenshot = pyautogui.screenshot()
            screenshot.save("screen.png")
            with open("screen.png", "rb") as photo:
                bot.send_photo(CHAT_ID, photo, caption="📸 **Screen Capture**")
        except Exception as e:
            bot.send_message(CHAT_ID, f"Error taking screenshot: {e}")

    # SYSTEM INFO
    elif call.data == "info":
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory()
        
        # Calculate time left
        elapsed = (datetime.now() - state["start_time"]).total_seconds() / 60
        left = state["duration"] - elapsed
        
        info_text = (
            f"📊 **System Status**\n"
            f"cpu: {cpu}%\n"
            f"ram: {ram.percent}%\n"
            f"uptime: {int(elapsed)} mins\n"
            f"remaining: {int(left)} mins"
        )
        bot.edit_message_text(info_text, call.message.chat.id, call.message.message_id, reply_markup=get_main_menu())

    # EXTEND TIME
    elif call.data == "extend":
        if state["duration"] + 30 > 355: # Hard limit GitHub ~6h
            bot.answer_callback_query(call.id, "❌ Cannot extend. Max GitHub limit (6h) reached.")
        else:
            state["duration"] += 30
            bot.answer_callback_query(call.id, "✅ Extended by 30 mins.")
            # Refresh info to show new time
            callback_handler(type('obj', (object,), {'data': 'info', 'message': call.message, 'id': call.id}))

    # KILL SWITCH
    elif call.data == "kill":
        bot.edit_message_text("💀 **Killing Session...**\nRunner will shut down immediately.", 
                              call.message.chat.id, call.message.message_id)
        state["active"] = False # Breaks the loop
        os.system("shutdown /s /t 1")

# --- CORE LOGIC ---

def start_rdp():
    try:
        # Inject PIN into command
        cmd = state["crd_cmd"]
        pin = state["pin"]
        
        # PowerShell command construction to include PIN
        full_cmd = f'$pin="{pin}"; ' + cmd.replace('remoting_start_host.exe"', 'remoting_start_host.exe" --pin=$pin')
        
        # Execute
        subprocess.run(["powershell", "-Command", full_cmd], shell=True)
        
        bot.send_message(CHAT_ID, "🖥️ **RDP IS READY!**\nLogin using your PIN now.", reply_markup=get_main_menu())
        
        # Start Monitor Loop
        monitor_loop()
        
    except Exception as e:
        bot.send_message(CHAT_ID, f"❌ Fatal Error: {str(e)}")

def monitor_loop():
    while state["active"]:
        now = datetime.now()
        end_time = state["start_time"] + timedelta(minutes=state["duration"])
        remaining_seconds = (end_time - now).total_seconds()
        remaining_minutes = remaining_seconds / 60
        
        # Time's up
        if remaining_seconds <= 0:
            bot.send_message(CHAT_ID, "🛑 **Time Limit Reached.** Shutting down runner.")
            os.system("shutdown /s /t 1")
            break
            
        # Warning 30 mins
        if 29 < remaining_minutes < 31 and not state["warned_30"]:
            bot.send_message(CHAT_ID, "⚠️ **WARNING: 30 MINUTES LEFT!**\nBackup your data now or Extend time.", reply_markup=get_main_menu())
            state["warned_30"] = True
            
        time.sleep(10)

# Start Bot
print("Bot Started...")
bot.infinity_polling()
