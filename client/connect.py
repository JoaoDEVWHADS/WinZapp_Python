import os
import sys
import threading
import socketio
import wx
import requests
from i18n import I18n
from websocket_client import WebSocketClient
from traceback import format_exc
import json
import base64
from io import BytesIO

class Connect:
    def __init__(self, main_window):
        self.main_window = main_window
        #initialize i18n
        self.i18n = I18n(self.main_window)
        self.i18n.get_language()
        self.connection_mode = "phone"  # Default mode: qrcode or phone

    def check_connection_status(self):
        #Check if token file exists and WA_token is  available in settings
        token_path = os.path.join(os.getcwd(), "data", "token.tk")
        private_info = self.main_window.settings.get("privateinfo", {})
        if os.path.exists(token_path) and private_info.get("WA_token"):
            return True
        return False

    def show_connection_dial(self):
        self.connection_dial = wx.Dialog(None, title=self.i18n.t("connect_phone").format(app_name=self.main_window.app_name), size=(400, 500))
        
        # QR-CODE Panel
        self.qrcode_panel = wx.Panel(self.connection_dial)
        self.qrcode_instructions = wx.StaticText(self.qrcode_panel, label=self.i18n.t("qrcode_instructions"))
        self.qrcode_image = wx.StaticBitmap(self.qrcode_panel, size=(300, 300))
        self.switch_to_phone_btn = wx.Button(self.qrcode_panel, label=self.i18n.t("connect_with_phone"))
        self.switch_to_phone_btn.Bind(wx.EVT_BUTTON, self.on_switch_to_phone)
        
        qrcode_sizer = wx.BoxSizer(wx.VERTICAL)
        qrcode_sizer.Add(self.qrcode_instructions, 0, wx.ALL | wx.CENTER, 10)
        qrcode_sizer.Add(self.qrcode_image, 0, wx.ALL | wx.CENTER, 10)
        qrcode_sizer.Add(self.switch_to_phone_btn, 0, wx.ALL | wx.CENTER, 10)
        self.qrcode_panel.SetSizer(qrcode_sizer)
        
        # Hide QR-CODE panel by default
        self.qrcode_panel.Hide()
        
        # Phone Number Panel
        self.phone_panel = wx.Panel(self.connection_dial)
        self.phone_number_label = wx.StaticText(self.phone_panel, label=self.i18n.t("enter_phone"))
        self.phone_field = wx.TextCtrl(self.phone_panel, style=wx.TE_CENTER | wx.TE_PROCESS_ENTER | wx.TE_DONTWRAP)
        self.continue_btn = wx.Button(self.phone_panel, label=self.i18n.t("continue"))
        self.continue_btn.Bind(wx.EVT_BUTTON, self.on_continue)
        self.phone_field.Bind(wx.EVT_TEXT_ENTER, self.on_continue)
        self.switch_to_qrcode_btn = wx.Button(self.phone_panel, label=self.i18n.t("connect_with_qrcode"))
        self.switch_to_qrcode_btn.Bind(wx.EVT_BUTTON, self.on_switch_to_qrcode)
        
        phone_sizer = wx.BoxSizer(wx.VERTICAL)
        phone_sizer.Add(self.phone_number_label, 0, wx.ALL | wx.CENTER, 10)
        phone_sizer.Add(self.phone_field, 0, wx.ALL | wx.EXPAND, 10)
        phone_sizer.Add(self.continue_btn, 0, wx.ALL | wx.CENTER, 10)
        phone_sizer.Add(self.switch_to_qrcode_btn, 0, wx.ALL | wx.CENTER, 10)
        self.phone_panel.SetSizer(phone_sizer)
        
        # Quit button
        self.quit_btn = wx.Button(self.connection_dial, wx.ID_CANCEL, "&Sair")
        self.quit_btn.Bind(wx.EVT_BUTTON, self.on_quit_from_connect)
        
        # Bind close event
        self.connection_dial.Bind(wx.EVT_CLOSE, self.on_dialog_close)
        
        # Main sizer
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        main_sizer.Add(self.qrcode_panel, 1, wx.ALL | wx.EXPAND, 5)
        main_sizer.Add(self.phone_panel, 1, wx.ALL | wx.EXPAND, 5)
        main_sizer.Add(self.quit_btn, 0, wx.ALL | wx.CENTER, 5)
        self.connection_dial.SetSizer(main_sizer)
        
        self.connection_dial.ShowModal()
    
    def on_switch_to_phone(self, event):
        # Set connection mode to phone
        self.connection_mode = "phone"
        
        # Disconnect WebSocket when switching to phone mode
        if hasattr(self.main_window, 'ws') and self.main_window.ws and self.main_window.ws.sio.connected:
            self.main_window.ws.sio.disconnect()
        
        self.qrcode_panel.Hide()
        self.phone_panel.Show()
        self.connection_dial.Layout()
        self.phone_field.SetFocus()

    
    def on_switch_to_qrcode(self, event):
        # Set connection mode to qrcode
        self.connection_mode = "qrcode"
        
        self.phone_panel.Hide()
        self.qrcode_panel.Show()
        self.connection_dial.Layout()
        
        if not hasattr(self, 'qrcode_connection_started'):
            # First time: start full QR-CODE connection
            self.start_qrcode_connection()
        else:
            # Already tried QR-CODE before: just reconnect WebSocket
            self.reconnect_websocket()
        
        self.main_window.qrcode_loaded_sound.play()
        self.main_window.output(self.i18n.t("qrcode_instructions"))
    
    def start_qrcode_connection(self):
        """Initiates QR-CODE connection without user interaction"""
        self.qrcode_connection_started = True
        try:
            # Ensure messages_set_completed is set to False
            self.main_window.settings["status"]["messages_set_completed"] = False
            self.main_window.save_settings()
            
            # Generate token if not already set
            if not self.main_window.settings.get("privateinfo", {}).get("WA_token"):
                self.main_window.token = self.generate_random_token()
                if "privateinfo" not in self.main_window.settings:
                    self.main_window.settings["privateinfo"] = {}
                self.main_window.settings["privateinfo"]["WA_token"] = self.main_window.token
            else:
                self.main_window.token = self.main_window.settings.get("privateinfo", {}).get("WA_token")
            
            # Create instance
            url = f"{self.main_window.authentication_server}:{self.main_window.authentication_port}/create_instance/"
            data = {
                "name": self.main_window.token,
                "token": self.main_window.token
            }
            response = requests.post(url, json=data, verify=False)
            print(response)
            
            # Save settings
            self.main_window.save_settings()
            
            # Set websocket client
            self.main_window.ws = WebSocketClient(self.main_window, self, self.main_window.token)
            
            # Connect instance without number parameter for QR-CODE
            url = f"{self.main_window.evolution_server}:{self.main_window.evolution_port}/instance/connect/{self.main_window.token}/"
            headers = {
                "apikey": self.main_window.token,
                "Content-Type": "application/json"
            }
            
            response = requests.get(url, verify=False, headers=headers)
            response_data = response.json()
            print(response_data)
            
            if response_data.get("base64"):
                # Connect WebSocket
                self.main_window.connect_websocket()
                # Display QR-CODE image
                self.display_qrcode_image(response_data.get("base64"))
            else:
                wx.MessageBox(self.i18n.t("no_QRcode_received").format(app_name=self.main_window.app_name), self.i18n.t("connection_error"), wx.OK | wx.ICON_ERROR)
                
        except Exception as e:
            self.main_window.error_sound.play()
            wx.MessageBox(f"{self.i18n.t('connection_failed').format(app_name=self.main_window.app_name)} {format_exc()}", self.i18n.t("connection_error").format(app_name=self.main_window.app_name), wx.OK | wx.ICON_ERROR)
    
    def display_qrcode_image(self, base64_string):
        """Decodes and displays the base64 QR-CODE image"""
        try:
            # Remove data URI prefix if present
            if "," in base64_string:
                base64_string = base64_string.split(",")[1]
            
            # Decode base64 to image
            image_data = base64.b64decode(base64_string)
            image = wx.Image(BytesIO(image_data))
            
            # Scale image if needed
            width, height = 300, 300
            image = image.Scale(width, height, wx.IMAGE_QUALITY_HIGH)
            
            # Convert to bitmap and display
            bitmap = wx.Bitmap(image)
            self.qrcode_image.SetBitmap(bitmap)
            
            # Play sound notification
            self.main_window.pairing_code_updated_sound.play()
            
        except Exception as e:
            print(f"Error displaying QR-CODE: {format_exc()}")

    def reconnect_websocket(self):
        """Reconnects WebSocket for QR-CODE mode (instance already created)"""
        try:
            self.main_window.connect_websocket()
        except Exception as e:
            self.main_window.error_sound.play()
            wx.MessageBox(f"{self.i18n.t('websocket_init_failed')} {format_exc()}", self.i18n.t("connection_error"), wx.OK | wx.ICON_ERROR)

    def on_continue(self, event):
        #Tries to create the instance
        try:
            url = f"{self.main_window.authentication_server}:{self.main_window.authentication_port}/create_instance/"
            self.phone_number = self.phone_field.GetValue()
            #Ensure messages_set_completed is set to False
            self.main_window.settings["status"]["messages_set_completed"] = False
            self.main_window.save_settings()
            #Check if the user has already tried to connect with this number
            if self.main_window.settings.get("privateinfo", {}).get("WA_phone_number", "") == self.phone_number and self.main_window.settings.get("privateinfo", {}).get("WA_token", ""):
                #Assume token available
                self.main_window.token = self.main_window.settings.get("privateinfo", {}).get("WA_token", "")
            else:
                self.main_window.token = self.generate_random_token()
                #Set the new token and phone number in settings
                if "privateinfo" not in self.main_window.settings:
                    self.main_window.settings["privateinfo"] = {}
                self.main_window.settings["privateinfo"]["WA_phone_number"] = self.phone_number
                self.main_window.settings["privateinfo"]["WA_token"] = self.main_window.token
            #Create new instance
            data = {
                "name": self.main_window.token,
                "number": self.phone_number,
                "token": self.main_window.token
            }
            response = requests.post(url, json=data, verify=False)
            response_data = response.json()
            print(response_data)

            #Save settings
            self.main_window.save_settings()
            #Set websocket client
            self.main_window.ws = WebSocketClient(self.main_window, self, self.main_window.token)
            #Connect instance
            url = f"{self.main_window.evolution_server}:{self.main_window.evolution_port}/instance/connect/{self.main_window.token}/"
            querystring = {"number": self.phone_number}
            headers = {
                "apikey": self.main_window.token,
                "Content-Type": "application/json"
            }

            response = requests.get(url, params=querystring, verify=False, headers=headers)
            response_data = response.json()
            print(response_data)

            if response_data.get("pairingCode"):
                #Connect WebSocket
                self.main_window.connect_websocket()
                self.show_pairing_dial(response_data.get("pairingCode"))
            else:
                wx.MessageBox(self.i18n.t("no_pairing_code_received").format(app_name=self.main_window.app_name), self.i18n.t("connection_error"), wx.OK | wx.ICON_ERROR)

        except Exception as e:
            self.main_window.error_sound.play()
            wx.MessageBox(f"{self.i18n.t('connection_failed').format(app_name=self.main_window.app_name)} {format_exc()}", self.i18n.t('connection_error').format(app_name=self.main_window.app_name), wx.OK | wx.ICON_ERROR)

    def generate_random_token(self):
        return os.urandom(16).hex()

    def show_pairing_dial(self, pairing_code):
        self.pairing_dial = wx.Dialog(self.connection_dial, title=self.i18n.t("pairing_dial_intro"), size=(300, 150))
        self.pairing_instructions = wx.StaticText(self.pairing_dial, label=self.i18n.t("pairing_instructions"))
        self.pairing_code_label = wx.StaticText(self.pairing_dial, label=self.i18n.t("pairing_code_label"))
        self.pairing_code_field = wx.TextCtrl(self.pairing_dial, style=wx.TE_CENTER | wx.TE_READONLY | wx.TE_DONTWRAP, value=pairing_code)
        self.cancel_btn = wx.Button(self.pairing_dial, label=self.i18n.t("cancel_pairing"))
        self.cancel_btn.Bind(wx.EVT_BUTTON, self.on_cancel_pairing)


        self.main_window.waiting_pairing_sound.play()
        self.pairing_dial.ShowModal()


    def on_cancel_pairing(self, event):
        self.pairing_dial.Destroy()
        self.main_window.ws.sio.disconnect()

    def on_dialog_close(self, event):
        # Disconnect WebSocket if connected
        if hasattr(self.main_window, 'ws') and self.main_window.ws and self.main_window.ws.sio.connected:
            self.main_window.ws.sio.disconnect()
        event.Skip()

    def on_quit_from_connect(self, event):
        sys.exit()