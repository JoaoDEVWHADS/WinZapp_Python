import os
import sys
import wx
import threading
from accessible import AccessibleSearchConversations, AccessibleRecordVoiceMessage
import json
import requests
from traceback import format_exc
from sound_system import SoundSystem
from datetime import datetime
from utils import format_number

class ConversationsPanel(wx.Panel):
    def __init__(self, main_window, parent):
        super().__init__(parent)
        self.main_window = main_window
        self.parent = parent
        self.chats_list = []
        self.chat_names = []
        self.conversation = None
        self.init_UI()
        self.create_accelerator_table()
        self.create_accel_conversation()

    def init_UI(self):
        self.search_label = wx.StaticText(self, label=self.main_window.i18n.t("search_conversations"), pos=(10, 250))
        self.search_field = wx.TextCtrl(self, size=(300, 25), pos=(10, 275), style=wx.TE_DONTWRAP)
        self.search_field.Bind(wx.EVT_TEXT, self.on_search_query_changed)
        self.search_field.SetAccessible(AccessibleSearchConversations("Ctrl+F"))
        self.conversations_label = wx.StaticText(self, label=self.main_window.i18n.t("conversations"), pos=(10,10))
        self.conversations_list = wx.ListCtrl(self, size=(380, 200), pos=(10, 40), style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.conversations_list.InsertColumn(0, self.main_window.i18n.t("conversations"), width=200)
        self.conversations_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_conversation_selected)
        self.conversations_list.Bind(wx.EVT_CONTEXT_MENU, self.on_conversations_context_menu)
        self.conversation_panel = wx.Panel(self)
        self.conversation_panel.Hide() #hidden by default
        # Messages list: single-column (name of the list is the header)
        self.messages_label = wx.StaticText(self.conversation_panel, label=self.main_window.i18n.t("messages"), pos=(10,10))
        self.messages_list = wx.ListCtrl(self.conversation_panel, size=(360, 150), pos=(10, 35), style=wx.LC_REPORT)
        self.messages_list.InsertColumn(0, self.main_window.i18n.t("messages"), width=360)

        self.message_label = wx.StaticText(self.conversation_panel, label=self.main_window.i18n.t("type_message"), pos=(10,200))
        self.message_field = wx.TextCtrl(self.conversation_panel, style=wx.TE_MULTILINE | wx.TE_PROCESS_ENTER | wx.TE_DONTWRAP, size=(300, 60), pos=(10, 225))
        self.message_field.Bind(wx.EVT_TEXT, self.on_change_message_field)
        self.send_message_btn = wx.Button(self.conversation_panel, label=self.main_window.i18n.t("send_message"), size=(150, 40), pos=(320, 175))
        self.send_message_btn.Hide() #hidden by default
        self.record_voice_message_btn = wx.Button(self.conversation_panel, label=self.main_window.i18n.t("record_voice_message"), size=(150, 40), pos=(320, 175))
        self.record_voice_message_btn.SetAccessible(AccessibleRecordVoiceMessage("Ctrl+R"))
        self.record_voice_message_btn.Bind(wx.EVT_BUTTON, self.on_record_voice_message)

    def on_conversation_selected(self, event):
        index = event.GetIndex()
        try:
            self.navigate_to_conversation(self.chats_list[index])
        except Exception:
            return


    def navigate_to_conversation(self, conversation):
        self.conversation = conversation
        self.conversation_name = self.main_window.find_name_through_messages(conversation) or conversation.get("pushName", "") or format_number(conversation.get("remoteJid", ""))
        self.message_label.SetLabel(f"{self.main_window.i18n.t('type_message')} {self.conversation_name}")
        self.conversation_panel.Show()
        self.preselect_messages()
        self.message_field.SetFocus()
        #Mark conversation as read in background
        self.mark_as_read_thread = threading.Thread(target=self.main_window.mark_conversation_as_read, args=(self.conversation.get("remoteJid", ""),), daemon=True)
        self.mark_as_read_thread.start()
        #Clear the conversation search field if it has text
        if self.search_field.GetValue().strip():
            self.search_field.Clear()
        # Populate messages list from local store
        self.populate_messages()

    def preselect_messages(self):
        self.messages_list.Focus(0)
        self.messages_list.Select(0)

    def create_accelerator_table(self):
        #Set IDs
        self.ID_CTRL_F = wx.NewIdRef()
        #create accelerator table
        accel_tbl = wx.AcceleratorTable([
            (wx.ACCEL_CTRL, ord('F'), self.ID_CTRL_F)
        ])
        self.SetAcceleratorTable(accel_tbl)
        self.Bind(wx.EVT_MENU, self.on_ctrl_f, id=self.ID_CTRL_F)

    def create_accel_conversation(self):
        #Set IDs
        self.ID_CTRL_R = wx.NewIdRef()
        self.ID_ESC = wx.NewIdRef()
        self.CTRL_W = wx.NewIdRef()
        #create accelerator table
        accel_tbl = wx.AcceleratorTable([
            (wx.ACCEL_CTRL, ord('R'), self.ID_CTRL_R),
            (wx.ACCEL_NORMAL, wx.WXK_ESCAPE, self.ID_ESC),
            (wx.ACCEL_CTRL, ord('W'), self.CTRL_W)
        ])
        self.conversation_panel.SetAcceleratorTable(accel_tbl)
        self.Bind(wx.EVT_MENU, self.on_record_voice_message, id=self.ID_CTRL_R)
        self.Bind(wx.EVT_MENU, self.close_conversation, id=self.ID_ESC)
        self.Bind(wx.EVT_MENU, self.close_conversation, id=self.CTRL_W)


    def on_search_query_changed(self, event):
        #Save copy of chats and chat_names
        self.chats_list = list(self.main_window.chats.values())
        self.chat_names = list(self.main_window.chat_names)
        query = self.search_field.GetValue().lower()
        self.chats_list.clear()
        self.chat_names.clear()
        self.conversations_list.DeleteAllItems()
        for i, chat in enumerate(self.main_window.chats.values()):
            name = self.main_window.chat_names[i]
            if query in name.lower():
                self.conversations_list.Append((name,))
                self.chats_list.append(chat)
                self.chat_names.append(name)
        self.main_window.preselect_conversations()

    def on_ctrl_f(self, event):
        self.search_field.SetFocus()

    def on_change_message_field(self, event):
        msg = self.message_field.GetValue()
        if msg.strip():
            self.send_message_btn.Show()
            self.record_voice_message_btn.Hide()
        else:
            self.send_message_btn.Hide()
            self.record_voice_message_btn.Show()

    def on_record_voice_message(self, event):
        pass

    def close_conversation(self, event):
        self.conversation_panel.Hide()
        self.conversations_list.SetFocus()

    def on_conversations_context_menu(self, event):
        # Only show context menu if a conversation is selected
        selected_index = self.conversations_list.GetFirstSelected()
        if selected_index == -1:
            return
        
        # Create context menu
        menu = wx.Menu()
        close_item = menu.Append(wx.ID_ANY, f"{self.main_window.i18n.t('close_conversation')}\tCtrl+W")
        
        # Bind menu item to close_conversation method
        self.Bind(wx.EVT_MENU, self.on_context_menu_close, close_item)
        
        # Show the menu
        self.PopupMenu(menu)
        menu.Destroy()

    def on_context_menu_close(self, event):
        # Only close if conversation panel is visible
        if self.conversation_panel.IsShown():
            self.close_conversation(event)

    def _extract_timestamp(self, msg):
        # Use API field `messageTimestamp` (seconds). 
        if not isinstance(msg, dict):
            return None
        ts = msg.get('messageTimestamp')
        if ts is None:
            return None
        try:
            return int(ts)
        except Exception:
            return None

    def _format_date(self, ts):
        if not ts:
            return ""
        try:
            dt = datetime.fromtimestamp(int(ts))
            today = datetime.now()
            if dt.date() == today.date():
                return dt.strftime("%H:%M")
            return dt.strftime("%d/%m/%Y %H:%M")
        except Exception:
            return ""

    def _format_duration(self, seconds):
        """Format duration in seconds to a human-readable string."""
        if seconds is None:
            return ""
        
        try:
            seconds = int(seconds)
        except (ValueError, TypeError):
            return ""
        
        i18n = self.main_window.i18n
        
        if seconds < 60:
            # Less than a minute: "X segundos" or "1 segundo"
            if seconds == 1:
                return f"{seconds} {i18n.t('second')}"
            else:
                return f"{seconds} {i18n.t('seconds')}"
        elif seconds < 3600:
            # Less than an hour: "X minutos e Y segundos"
            minutes = seconds // 60
            secs = seconds % 60
            
            min_str = i18n.t('minute') if minutes == 1 else i18n.t('minutes')
            sec_str = i18n.t('second') if secs == 1 else i18n.t('seconds')
            
            return f"{minutes} {min_str} {i18n.t('and')} {secs} {sec_str}"
        else:
            # One hour or more: "X horas, Y minutos e Z segundos"
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            secs = seconds % 60
            
            hour_str = i18n.t('hour') if hours == 1 else i18n.t('hours')
            min_str = i18n.t('minute') if minutes == 1 else i18n.t('minutes')
            sec_str = i18n.t('second') if secs == 1 else i18n.t('seconds')
            
            return f"{hours} {hour_str}, {minutes} {min_str} {i18n.t('and')} {secs} {sec_str}"

    def _get_message_content(self, msg):
        """Extract message content based on message type."""
        message_type = msg.get('messageType', 'conversation')
        message_obj = msg.get('message') or {}
        
        if not isinstance(message_obj, dict):
            return self.main_window.i18n.t('unsupported_message')
        
        i18n = self.main_window.i18n
        
        # Supported message types
        if message_type == "audioMessage":
            # Extract audio information
            audio_msg = message_obj.get('audioMessage', {})
            if isinstance(audio_msg, dict):
                duration = audio_msg.get('seconds')
                duration_str = self._format_duration(duration)
                return f"{i18n.t('message_type_audio')}, {i18n.t('duration')}: {duration_str}"
            return i18n.t('message_type_audio')
        elif message_type == 'conversation':
            # Text message
            return message_obj.get('conversation', '')
        else:
            # Unsupported message type
            return i18n.t('unsupported_message')

    def _map_status(self, msg):
        # Map common ack/status fields to localized strings
        i18n = self.main_window.i18n
        # If MessageUpdate is empty or missing, do not show any status.
        updates = msg.get('MessageUpdate')
        if isinstance(updates, list) and len(updates) > 0:
            # Normalize statuses and prioritize READ > DELIVERY_* > SENT
            statuses = []
            for u in updates:
                if isinstance(u, dict):
                    st = (u.get('status') or u.get('ack') or "")
                    statuses.append(str(st).upper())
            # Check for READ
            for s in statuses:
                if 'READ' in s:
                    return i18n.t('status_read')
            # Check for delivery acknowledgements
            for s in statuses:
                if 'DELIVERED' in s or 'DELIVERY_ACK' in s:
                    return i18n.t('status_delivered')
            # Check for sent/ack
            for s in statuses:
                if 'SENT' in s or 'ACK' in s:
                    return i18n.t('status_sent')

        # If no valid MessageUpdate entries, do not display status
        return ""

    def populate_messages(self):
        self.messages_list.DeleteAllItems()
        # Extract messages records from API response shape.
        # Expected: conversation['messages'] == {'messages': {'records': [...] , ...}, ...}
        messages_container = self.conversation.get('messages', {}) if self.conversation else {}
        messages = []
        if isinstance(messages_container, dict):
            # Wrapper contains 'messages' -> {'records': [...]}
            inner = messages_container.get('messages')
            if isinstance(inner, dict) and isinstance(inner.get('records'), list):
                messages = inner.get('records', [])
        # sort by timestamp if possible
        try:
            messages_sorted = sorted(messages, key=lambda m: self._extract_timestamp(m) or 0)
        except Exception:
            messages_sorted = messages

        for msg in messages_sorted:
            #If reaction message, ignore
            if msg.get("messageType", "") == "reactionMessage":
                continue
            # According to API sample: record has `messageTimestamp`, `message.conversation`, `pushName`, `key.fromMe`, `MessageUpdate`
            ts = self._extract_timestamp(msg)
            time_str = self._format_date(ts) if ts else ""
            # Extract message content based on type
            body = self._get_message_content(msg)
            # sender info
            if msg.get('key', {}).get('fromMe'):
                sender_label = self.main_window.i18n.t('sender_you')
            else:
                sender_label = msg.get("pushName", "")
            status = self._map_status(msg)
            body = (body or '').replace('\n', ' ')
            pieces = [f"{sender_label}: {body}" ]
            if time_str:
                pieces.append(f", {time_str}")
            if status:
                # append status after comma
                pieces[-1] = pieces[-1] + f", {status}"
            line = " ".join(pieces)
            self.messages_list.Append((line,))