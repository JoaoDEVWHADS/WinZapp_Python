import os
import sys
import threading
import requests
import base64
import socketio
from accessible_output2 import outputs
from websocket_client import WebSocketClient
from sound_system import SoundSystem, Sound
from i18n import I18n
from utils import encrypt, decrypt, encrypt_json, decrypt_json, generate_and_save_key, retrieve_key, format_number, check_internet_connection
import wx
from connect import Connect
from navigation import NavigationPanel
from conversations import ConversationsPanel
import json
from traceback import format_exc, format_exception
import pyperclip

class MainWindow(wx.Frame):
    def __init__(self, title):
        super().__init__(None, title=title)

        #Initialize screen reader/sapi output
        self.speak_output = outputs.auto.Auto()

        #Initialize sound system
        self.sound_system = SoundSystem(self, sound_dir=os.path.join(os.getcwd(), "sounds"))
        self.sound_system.start()
        self.load_sounds()
        self.settings = {}
        self.load_settings()

        #Initialize helper classes
        self.connect = Connect(self)
        self.i18n = I18n(self)
        self.i18n.get_language()

        #bind exception global handler for unexpected errors
        sys.excepthook = self.exception_handler

        #Get connection settings
        self.authentication_server = self.settings.get("connection", {}).get("authentication_server", "127.0.0.1")
        self.authentication_port = self.settings.get("connection", {}).get("authentication_port", 8081)
        self.evolution_server = self.settings.get("connection", {}).get("evolution_server", "127.0.0.1")
        self.evolution_port = self.settings.get("connection", {}).get("evolution_port", 8080)

        #Check Internet Connection
        self.offline_mode = not check_internet_connection()
        #Play startup sound
        self.startup_sound.play()
        self.ws = WebSocketClient(self, self.connect)

        #Check for what window should be shown
        if not self.connect.check_connection_status():
            self.connect.show_connection_dial()
        self.retrieve_token()
        self.prepare_sync()
        #Connect WebSocket if not Offline
        if not self.offline_mode:
            self.connect.connect_websocket(self.token)
        self.init_UI()


    def init_UI(self):
        if self.offline_mode:
            self.SetTitle(f"{self.i18n.t('app_name')} - {self.i18n.t('offline_mode')}")
        self    .SetSize((400, 300))
        self.main_panel = wx.Panel(self)
        self.content_panel = wx.Panel(self.main_panel)
        self.conversations_panel = ConversationsPanel(self, self.content_panel)
        self.navigation_panel = NavigationPanel(self, self.main_panel)
        self.create_accelerator_table()
        self.Show()
        #Set offline chats for the first time
        self.set_chats()
        app.MainLoop()

    def create_accelerator_table(self):
        #Set IDs
        self.ID_ALT_1 = wx.NewIdRef()
        #create accelerator table
        accel_tbl = wx.AcceleratorTable([
            (wx.ACCEL_ALT, ord('1'), self.ID_ALT_1)
        ])
        self.SetAcceleratorTable(accel_tbl)
        self.Bind(wx.EVT_MENU, self.on_alt_1, id=self.ID_ALT_1)

    def on_alt_1(self, event):
        panels = self.content_panel.GetChildren()
        for panel in panels:
            panel.Hide()
        self.conversations_panel.Show()
        self.conversations_panel.conversations_list.SetFocus()
        #Check if list has selection
        if self.conversations_panel.conversations_list.GetFocusedItem() != -1 and self.conversations_panel.conversations_list.GetItemCount() > 0:#Output the current focused conversation
            self.output(self.conversations_panel.conversations_list.GetItemText(self.conversations_panel.conversations_list.GetFocusedItem()))

    def output(self, text, interrupt=False):
        self.speak_output.output(text, interrupt=interrupt)

    def load_settings(self):
        try:
            self.settings = json.load(open(os.path.join(os.getcwd(), "data", "settings.json"), "r"))
        except Exception as e:
            self.error_sound.play()
            wx.MessageBox(f"{self.i18n.t["settings_load_failed"]} {format_exc()}", self.i18n.t["error"], wx.OK | wx.ICON_ERROR)
            sys.exit()

    def save_settings(self):
        try:
            json.dump(self.settings, open(os.path.join(os.getcwd(), "data", "settings.json"), "w"), indent=4)
        except Exception as e:
            self.error_sound.play()
            wx.MessageBox(f"{self.i18n.t["settings_save_failed"]} {format_exc()}", self.i18n.t["error"], wx.OK | wx.ICON_ERROR)

    def load_sounds(self):
        self.startup_sound = Sound(self.sound_system, "startup.ogg")
        self.error_sound = Sound(self.sound_system, "error.ogg")
        self.waiting_pairing_sound = Sound(self.sound_system, "waiting_pairing.ogg")
        self.pairing_code_updated_sound = Sound(self.sound_system, "pairing_code_updated.ogg")
        self.connected_sound = Sound(self.sound_system, "connected.ogg")
        self.synchronizing_sound = Sound(self.sound_system, "synchronizing.ogg")
        self.sync_complete_sound = Sound(self.sound_system, "sync_complete.ogg")
        self.offline_mode_sound = Sound(self.sound_system, "offline_mode.ogg")

    def retrieve_token(self):
        try:
            with open(os.path.join(os.getcwd(), "data", "token.tk"), "r") as token_file:
                self.token = token_file.read().strip()
        except Exception as e:
            self.error_sound.play()
            wx.MessageBox(f"{self.i18n.t('token_retrieval_failed')} {format_exc()}", self.i18n.t("error"), wx.OK | wx.ICON_ERROR)
            sys.exit()

    def prepare_sync(self):
        self.generate_secret_key()
        self.key = self.retrieve_secret_key()
        self.create_basic_files()

        #Get Local Chats
        self.chats = self.get_chats()
        self.contacts = self.get_contacts()
        if not self.offline_mode:
            self.sync_thread = threading.Thread(target=self.start_sync, daemon=True)
            self.sync_thread.start()
        else:
            self.offline_mode_sound.play()
            self.output(self.i18n.t("offline_mode_enabled"))
        self.monitor_thread = threading.Thread(target=self.monitor_internet_connection, daemon=True)
        self.monitor_thread.start()

    def start_sync(self):
        self.connected_sound.play()
        self.chats = self.get_remote_chats()
        self.normalize_chats()
        self.contacts = self.get_remote_contacts()
        self.synchronizing_sound.play()
        self.SetTitle(f"{self.i18n.t('app_name')} - {self.i18n.t('synchronizing')}")
        self.output(self.i18n.t("synchronization_started"), interrupt=True)
        self.sync_remote_chats()
        self.sync_complete_sound.play()
        self.SetTitle(f"{self.i18n.t('app_name')}")
        self.output(self.i18n.t("sync_complete"))
        wx.CallAfter(self.preselect_conversations)

    def create_basic_files(self):
        data_dir = os.path.join(os.getcwd(), "data")
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)

        #Create empty messages.dat if not exists
        messages_file = os.path.join(data_dir, "messages.dat")
        if not os.path.isfile(messages_file):
            with open(messages_file, "wb") as f:
                f.write(encrypt_json({"chats": {}, "contacts": {}}, self.key))

        #Create media/voice message directories
        media_dir = os.path.join(data_dir, "media")
        voice_messages_dir = os.path.join(data_dir, "voice_messages")
        if not os.path.exists(media_dir):
            os.makedirs(media_dir)
        if not os.path.exists(voice_messages_dir):
            os.makedirs(voice_messages_dir)

        #Create stderr/stdout log files
        log_dir = os.path.join(data_dir, "log")
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        stderr_log = os.path.join(log_dir, "stderr.log")
        stdout_log = os.path.join(log_dir, "stdout.log")
        if not os.path.isfile(stderr_log):
            open(stderr_log, "w").close()
        if not os.path.isfile(stdout_log):
            open(stdout_log, "w").close()
        #Set stderr and stdout
        sys.stderr = open(stderr_log, "a")
        sys.stdout = open(stdout_log, "a")

    def get_chats(self):
        messages_file = os.path.join(os.getcwd(), "data", "messages.dat")
        try:
            with open(messages_file, "rb") as f:
                encrypted_data = f.read()
                if encrypted_data:
                    decrypted_data = decrypt_json(encrypted_data, self.key)
                    return decrypted_data.get("chats", {})
                else:
                    return []
        except Exception as e:
            self.error_sound.play()
            wx.MessageBox(f"{self.i18n.t('chat_load_failed')} {format_exc()}", self.i18n.t("error"), wx.OK | wx.ICON_ERROR)
            return []

    def get_remote_chats(self):
        url = f"https://{self.evolution_server}:{self.evolution_port}/chat/findChats/{self.token}"
        headers = {
            "apikey": self.token,
            "Content-Type": "application/json"
        }
        try:
            response = requests.post(url, headers=headers, verify=False)
            response_data = response.json()
            chats = {}
            for chat in response_data:
                chat["messages"] = {}
                chats[chat.get("remoteJid", "")] = chat
            self.save_data(chats, self.contacts)
            return chats
        except Exception as e:
            self.error_sound.play()
            wx.MessageBox(f"{self.i18n.t('chat_retrieval_failed')} {format_exc()}", self.i18n.t("error"), wx.OK | wx.ICON_ERROR, self)

    def normalize_chats(self):
        for key, chat in self.chats.items():
            if chat["unreadCount"] is None:
                chat["unreadCount"] = 0
            self.chats[key] = chat

    def save_data(self, chats, contacts):
        #Save back to file
        messages_file = os.path.join(os.getcwd(), "data", "messages.dat")
        try:
            encrypted_data = encrypt_json({"chats": chats, "contacts": contacts}, self.key)
            with open(messages_file, "wb") as f:
                f.write(encrypted_data)
        except Exception as e:
            self.error_sound.play()
            wx.MessageBox(f"{self.i18n.t('data_save_failed')} {format_exc()}", self.i18n.t("error"), wx.OK | wx.ICON_ERROR)

    def get_contacts(self):
        messages_file = os.path.join(os.getcwd(), "data", "messages.dat")
        try:
            with open(messages_file, "rb") as f:
                encrypted_data = f.read()
                if encrypted_data:
                    decrypted_data = decrypt_json(encrypted_data, self.key)
                    return decrypted_data.get("contacts", {})
                else:
                    return {}
        except Exception as e:
            self.error_sound.play()
            wx.MessageBox(f"{self.i18n.t('contact_load_failed')} {format_exc()}", self.i18n.t("error"), wx.OK | wx.ICON_ERROR)
            return {}

    def get_remote_contacts(self):
        url = f"https://{self.evolution_server}:{self.evolution_port}/chat/findContacts/{self.token}"
        headers = {
            "apikey": self.token,
            "Content-Type": "application/json"
        }
        try:
            response = requests.post(url, headers=headers, verify=False)
            response_data = response.json()
            contacts = {}
            for contact in response_data:
                if contact.get("type", "") == "contact":
                    contacts[contact.get("remoteJid", "")] = contact
            self.save_data(self.chats, contacts)
            self.contact_ids = [contact.get("remoteJid", "") for contact in response_data]
            return contacts
        except Exception as e:
            self.error_sound.play()
            wx.MessageBox(f"{self.i18n.t('contact_retrieval_failed')} {format_exc()}", self.i18n.t("error"), wx.OK | wx.ICON_ERROR, self)

    def set_chats(self):
        self.chat_names = []
        for chat in self.chats.values():
            self.chat_names.append(chat.get("pushName", "") or format_number(chat.get("remoteJid", "")))
        #Checks if window is still open
        if self.IsShown():
            self.add_chats_to_ui()
        #Save copy of chats and chat_names
        self.conversations_panel.chats_list = list(self.chats.values())
        self.conversations_panel.chat_names = list(self.chat_names)
        self.preselect_conversations()

    def preselect_conversations(self):
        #Checks if window is still open
        if self.IsShown():
            self.conversations_panel.conversations_list.Focus(0)
            self.conversations_panel.conversations_list.Select(0)

    def sync_remote_chats(self):
        for chat in self.chats.values():
            self.sync_chat_messages(chat)

    def sync_chat_messages(self, chat):
        url = f"https://{self.evolution_server}:{self.evolution_port}/chat/findMessages/{self.token}"

        payload = { "where": { "key": { "remoteJid": chat.get("remoteJid", "")} } }
        headers = {
            "apikey": self.token,
            "Content-Type": "application/json"
        }

        response = requests.post(url, json=payload, headers=headers, verify=False)
        response_data = response.json()
        chat["messages"] = response_data
        for message in chat["messages"].get("messages", {}).get("records", []):
            self.sync_if_media(message)
        if chat["messages"] != self.chats[chat.get("remoteJid", "")].get("messages", {}): #update only if necessary
            self.chats[chat.get("remoteJid", "")] = chat
            self.save_data(self.chats, self.contacts)
            #Checks if window is still open
            if self.IsShown():
                wx.CallAfter(self.set_chats)

    def sync_if_media(self, msg):
        #Check message type
        message_type = msg.get("messageType", "")
        if message_type == "audioMessage":
            try:
                self.handle_audio_message(msg)
            except Exception as e:
                #Ignore and download later if necessary
                pass
        return

    def handle_audio_message(self, msg):
        #First, check if the audio is already downloaded
        voice_messages_dir = os.path.join(os.getcwd(), "data", "voice_messages")
        audio_file_path = os.path.join(voice_messages_dir, f"{msg.get('key', {}).get('id', '')}.msv")
        if os.path.isfile(audio_file_path):
            return

        base64_audio = self.get_base64_from_media(msg)
        audio_content = base64.b64decode(base64_audio)
        self.save_audio_locally(msg, audio_content)

    def get_base64_from_media(self, media):
        url = f"https://{self.evolution_server}:{self.evolution_port}/chat/getBase64FromMediaMessage/{self.token}"
        payload = {
            "message": {"key": {"id": media.get("key", {}).get("id", "")}},
            "convertToMp4": False
        }
        headers = {
            "apikey": self.token,
            "Content-Type": "application/json"  
        }
        response = requests.post(url, json=payload, headers=headers, verify=False)
        if response.status_code == 201:
            return response.json().get("base64", "")
        return ""

    def save_audio_locally(self, msg, audio_content):
        voice_messages_dir = os.path.join(os.getcwd(), "data", "voice_messages")
        audio_file_path = os.path.join(voice_messages_dir, f"{msg.get('key', {}).get('id', '')}.msv")
        try:
            with open(audio_file_path, "wb") as audio_file:
                encrypted_audio = encrypt(audio_content, self.key)
                audio_file.write(encrypted_audio)
        except Exception as e:
            #Ignore audios that couldn't be saved for now
            pass

    def mark_conversation_as_read(self, remote_jid):
        pass

    def add_chats_to_ui(self):
        self.conversations_panel.conversations_list.DeleteAllItems()
        for index, chat in enumerate(self.chats.values()):
            string = f"\
            {self.chat_names[index]} \
            {f"{chat.get('unreadCount') or 0} {self.i18n.t('unread_messages') if int(chat.get('unreadCount')) > 1 else self.i18n.t('unread_message')} " if int(chat.get('unreadCount')) > 0 else ""}\
            "
            self.conversations_panel.conversations_list.Append((string,))

    def monitor_internet_connection(self):
        while True:
            is_connected = check_internet_connection()
            if is_connected and self.offline_mode:
                #Went online
                self.offline_mode = False
                wx.CallAfter(self.on_connection_restored)
            elif not is_connected and not self.offline_mode:
                #Went offline
                self.offline_mode = True
                wx.CallAfter(self.on_connection_lost)
            threading.Event().wait(5)  # Check every 5 seconds

    def on_connection_restored(self):
        self.output(self.i18n.t("connection_restored"), interrupt=True)
        self.SetTitle(f"{self.i18n.t('app_name')}")
        self.sync_thread = threading.Thread(target=self.start_sync, daemon=True)
        self.sync_thread.start()
        self.connect.connect_websocket(self.token)

    def on_connection_lost(self):
        self.output(self.i18n.t("connection_lost"), interrupt=True)
        self.offline_mode_sound.play()
        self.output(self.i18n.t("offline_mode_enabled"))
        self.SetTitle(f"{self.i18n.t('app_name')} - {self.i18n.t('offline_mode')}")

    def generate_secret_key(self):
        key_file = os.path.join(os.getcwd(), "data", "secret.key")
        if not os.path.isfile(key_file):
            generate_and_save_key(key_file)

    def retrieve_secret_key(self):
        key_file = os.path.join(os.getcwd(), "data", "secret.key")
        return retrieve_key(key_file)

    def exception_handler(self, exc_type, exc_value, exc_traceback):
        """Global exception handler for unexpected errors."""
        # Format the full traceback
        error_text = ''.join(format_exception(exc_type, exc_value, exc_traceback))

        #Play error sound
        self.error_sound.play()
        
        # Create error dialog
        dialog = wx.Dialog(None, title=self.i18n.t("error"), size=(600, 400), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        
        panel = wx.Panel(dialog)
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Error message
        message_text = wx.StaticText(panel, label=self.i18n.t("unexpected_error_message"))
        sizer.Add(message_text, 0, wx.ALL, 10)

        #Error details label
        details_label = wx.StaticText(panel, label=self.i18n.t("error_details"))
        sizer.Add(details_label, 0, wx.LEFT | wx.TOP, 10)
        
        # Error details text control (read-only, multiline)
        error_ctrl = wx.TextCtrl(panel, value=error_text, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP)
        sizer.Add(error_ctrl, 1, wx.ALL | wx.EXPAND, 10)
        
        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        # Copy button
        copy_btn = wx.Button(panel, label=self.i18n.t("copy_error_text"))
        copy_btn.Bind(wx.EVT_BUTTON, lambda evt: self.on_copy_error(error_text))
        button_sizer.Add(copy_btn, 0, wx.ALL, 5)
        
        # Close button
        close_btn = wx.Button(panel, id=wx.ID_CANCEL, label=self.i18n.t("close"))
        button_sizer.Add(close_btn, 0, wx.ALL, 5)
        
        sizer.Add(button_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 10)
        
        panel.SetSizer(sizer)
        
        # Show dialog
        dialog.ShowModal()
        dialog.Destroy()
    
    def on_copy_error(self, error_text):
        """Copy error text to clipboard."""
        try:
            pyperclip.copy(error_text)
            self.output(self.i18n.t("error_copied"), interrupt=True)
        except Exception:
            pass


if __name__ == "__main__":
    app = wx.App()
    frame = MainWindow(title="WinZapp")