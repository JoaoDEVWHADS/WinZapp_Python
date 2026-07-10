import os
import sys
import wx
from wx.adv import CommandLinkButton as CmdBtn
import json
import requests
from traceback import format_exc
from sound_system import SoundSystem
from datetime import datetime

class ConversationsPanel(wx.Panel):
    def __init__(self, main_window, parent):
        super().__init__(parent)
        self.main_window = main_window
        self.parent = parent
        self.init_UI()
        self.create_accelerator_table()

    def init_UI(self):
        self.conversations_label = wx.StaticText(self, label=self.main_window.i18n.t("conversations"), pos=(10,10))
        self.conversations_list = wx.ListCtrl(self, size=(380, 200), pos=(10, 40), style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.conversations_list.InsertColumn(0, self.main_window.i18n.t("conversations"), width=200)
        self.conversations_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_conversation_selected)
        self.conversation_panel = wx.Panel(self)
        self.conversation_panel.Hide() #hidden by default
        # Messages list: single-column (name of the list is the header)
        self.messages_label = wx.StaticText(self.conversation_panel, label=self.main_window.i18n.t("messages"), pos=(10,10))
        self.messages_list = wx.ListCtrl(self.conversation_panel, size=(360, 150), pos=(10, 35), style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.messages_list.InsertColumn(0, self.main_window.i18n.t("messages"), width=360)

        self.message_label = wx.StaticText(self.conversation_panel, label=self.main_window.i18n.t("type_message"), pos=(10,200))
        self.message_field = wx.TextCtrl(self.conversation_panel, style=wx.TE_MULTILINE | wx.TE_PROCESS_ENTER | wx.TE_DONTWRAP, size=(300, 60), pos=(10, 225))
        self.record_voice_message_btn = CmdBtn(self.conversation_panel, mainLabel=self.main_window.i18n.t("record_voice_message"), note="Ctrl+R", size=(150, 40), pos=(320, 225))
        self.record_voice_message_btn.Bind(wx.EVT_BUTTON, self.on_record_voice_message)

    def on_conversation_selected(self, event):
        # map the selected index to the chats order used when building the UI
        chats_list = list(self.main_window.chats.values())
        index = event.GetIndex()
        try:
            self.conversation = chats_list[index]
            # self.main_window.output(str(self.conversation.get("messages", [])))
        except Exception:
            return
        self.conversation_name = self.main_window.chat_names[index]
        self.message_label.SetLabel(f"{self.main_window.i18n.t('type_message')} {self.conversation_name}")
        self.conversation_panel.Show()
        self.message_field.SetFocus()
        # Populate messages list from local store
        self.populate_messages()

    def create_accelerator_table(self):
        #Set IDs
        self.ID_CTRL_R = wx.NewIdRef()
        self.ID_ESC = wx.NewIdRef()
        #create accelerator table
        accel_tbl = wx.AcceleratorTable([
            (wx.ACCEL_CTRL, ord('R'), self.ID_CTRL_R),
            (wx.ACCEL_NORMAL, wx.WXK_ESCAPE, self.ID_ESC),
        ])
        self.SetAcceleratorTable(accel_tbl)
        self.Bind(wx.EVT_MENU, self.on_record_voice_message, id=self.ID_CTRL_R)
        self.Bind(wx.EVT_MENU, self.close_conversation, id=self.ID_ESC)

    def on_record_voice_message(self, event):
        pass

    def close_conversation(self, event):
        self.conversation_panel.Hide()
        self.conversations_list.SetFocus()

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

    def _map_status(self, msg):
        # Map common ack/status fields to localized strings
        i18n = self.main_window.i18n
        # Prefer explicit MessageUpdate entries from API when present.
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
                if 'READ' in s or 'LIDA' in s:
                    return i18n.t('status_read')
            # Check for delivery acknowledgements
            for s in statuses:
                if 'DELIVERY' in s or 'DELIVERED' in s or 'DELIVERY_ACK' in s:
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
            # primary case: wrapper contains 'messages' -> {'records': [...]}
            inner = messages_container.get('messages')
            if isinstance(inner, dict) and isinstance(inner.get('records'), list):
                messages = inner.get('records', [])
            # alternate: records at top level of the container
            elif isinstance(messages_container.get('records'), list):
                messages = messages_container.get('records', [])
            else:
                # fallback: try find the first list value inside the dict
                for v in messages_container.values():
                    if isinstance(v, list):
                        messages = v
                        break
        elif isinstance(messages_container, list):
            messages = messages_container
        # sort by timestamp if possible
        try:
            messages_sorted = sorted(messages, key=lambda m: self._extract_timestamp(m) or 0)
        except Exception:
            messages_sorted = messages

        for msg in messages_sorted:
            # According to API sample: record has `messageTimestamp`, `message.conversation`, `pushName`, `key.fromMe`, `MessageUpdate`
            ts = self._extract_timestamp(msg)
            time_str = self._format_date(ts) if ts else ""
            # body is inside message.conversation for conversation messages
            body = ""
            message_obj = msg.get('message') or {}
            if isinstance(message_obj, dict):
                body = message_obj.get('conversation') or message_obj.get('text') or ''
            # sender info
            if msg.get('key', {}).get('fromMe'):
                sender_label = self.main_window.i18n.t('sender_you')
            else:
                sender_label = self.conversation_name or (msg.get('pushName') or '')
            status = self._map_status(msg)
            body = (body or '').replace('\n', ' ')
            # Build single-column line: "Remetente: Mensagem HH:MM, Status"
            pieces = [f"{sender_label}: {body}" ]
            if time_str:
                pieces.append(time_str)
            if status:
                # append status after comma
                if len(pieces) > 1:
                    pieces[-1] = pieces[-1] + f", {status}"
                else:
                    pieces[-1] = pieces[-1] + f", {status}"
            line = " ".join(pieces)
            self.messages_list.InsertItem(self.messages_list.GetItemCount(), line)