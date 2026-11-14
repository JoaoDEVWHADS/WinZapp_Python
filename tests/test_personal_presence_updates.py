"""An already populated personal dialog must expire activity without refocus.

Plain TextCtrl/timer models only; includes UTF-16/CRLF native positions.
"""
from types import SimpleNamespace
import threading

import pytest

from core import contact_presence as cache
from main_window.contact_presence import ContactPresenceMixin
from tests.test_contact_presence_freshness import PN, LID
from tests.test_contact_presence_views import I18n
from tests.test_presence_speech_gating import _Stub, _Timer
from ui.dialogs.conversation_data_dialog import ConversationDataDialog


class Text:
    def __init__(self, windows=False):
        self.text=''
        self.windows=windows
        self.selection=(0,0)
        self.caret=0
        self.focuses=self.writes=self.events=0

    def units(self, text):
        return len(text.replace('\n','\r\n').encode('utf-16-le'))//2 if self.windows else len(text)

    def SetValue(self, value):
        self.text=value
        self.selection=(0,0)
        self.caret=0
        self.writes+=1
        self.events+=1

    def ChangeValue(self, value):
        self.text=value
        self.selection=(0,0)
        self.caret=0
        self.writes+=1

    def SetFocus(self):
        self.focuses+=1

    def GetSelection(self):
        return self.selection

    def GetInsertionPoint(self):
        return self.caret

    def SetSelection(self, start, end):
        self.selection=(min(start,end),max(start,end))
        self.caret=end

    def GetLineLength(self, line):
        return self.units(self.text.split('\n')[line])

    def GetLastPosition(self):
        return self.units(self.text)

    def XYToPosition(self, x, y):
        return self.units(''.join(line+'\n' for line in self.text.split('\n')[:y]))+x

    def at(self, substring):
        return self.units(self.text[:self.text.index(substring)])


def dialog(owner, *, windows=False, jid=PN):
    text=Text(windows)
    view=SimpleNamespace(_mw=owner,_i18n=owner.i18n,_jid=jid,_name='Contact 🧑',
                         _closed=threading.Event(),_info_ctrl=text)
    ConversationDataDialog._populate_personal_unsafe(view,{'aboutText':'Biography 📝\nsecond line'})
    return view,text


@pytest.fixture
def live(monkeypatch):
    import main_window.chat_events as events
    clock,timers=[100],[]
    monkeypatch.setattr(cache.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(events.wx,'CallLater',lambda ms,fn:timers.append(fn) or _Timer())
    owner=_Stub(conversation_jid=PN)
    owner.i18n=I18n()
    owner._refresh_open_contact_presence_note=lambda:None
    return owner,clock,timers


@pytest.mark.parametrize('state,label',[('composing','typing_indicator'),('recording','recording_indicator')])
@pytest.mark.parametrize('end',['expiry','paused'])
def test_populated_dialog_expires_via_real_event_path_without_manual_render(live,state,label,end):
    owner,clock,timers=live
    owner.on_presence_update(PN,{PN:{'lastKnownPresence':state,'isOnline':False}})
    view,text=dialog(owner)
    assert label in text.text
    spoken=len(owner.speak_output.outputs)
    if end=='expiry':
        clock[0]=110
        timers[-1]()
    else:
        owner.on_presence_update(PN,{PN:{'lastKnownPresence':'paused','isOnline':False}})
    assert label not in text.text
    assert 'Biography 📝\nsecond line' in text.text
    assert text.focuses==1 and text.events==1
    assert len(owner.speak_output.outputs)==spoken


@pytest.mark.parametrize('windows',[False,True])
@pytest.mark.parametrize('where',['before','after','inside'])
@pytest.mark.parametrize('selection',['caret','forward','backward'])
def test_native_positions_keep_selection_and_caret_with_unicode_and_multiline(live,windows,where,selection):
    owner,clock,timers=live
    owner.on_presence_update(PN,{PN:{'lastKnownPresence':'composing','isOnline':False}})
    view,text=dialog(owner,windows=windows)
    token={'before':'Biography 📝','after':'chat_encryption_notice','inside':'typing_indicator'}[where]
    start=text.at(token)
    end=start if selection=='caret' else start+3
    text.SetSelection(end,start) if selection=='backward' else text.SetSelection(start,end)
    prior_caret=text.caret
    prior_selection=text.selection
    old_span_start=text.at('typing_indicator')
    old_span_end=text.at('chat_encryption_label')
    clock[0]=110
    timers[-1]()
    delta=old_span_end-old_span_start
    if where=='before':
        assert text.selection==prior_selection and text.caret==prior_caret
    elif where=='after':
        assert text.selection==tuple(pos-delta for pos in prior_selection)
        assert text.caret==prior_caret-delta
    else:
        assert text.selection==(old_span_start,old_span_start) and text.caret==old_span_start
    assert text.events==text.focuses==1 and 'typing_indicator' not in text.text


def test_repeated_activity_does_not_rewrite_text_and_switch_uses_current_state(live):
    owner,_,_=live
    owner.on_presence_update(PN,{PN:{'lastKnownPresence':'composing','isOnline':False}})
    view,text=dialog(owner)
    for _ in range(3):
        owner.on_presence_update(PN,{PN:{'lastKnownPresence':'composing','isOnline':False}})
    assert text.writes==1
    owner.on_presence_update(PN,{PN:{'lastKnownPresence':'recording','isOnline':False}})
    assert 'recording_indicator' in text.text and 'typing_indicator' not in text.text
    assert text.writes==2 and text.events==text.focuses==1


def test_mapped_lid_updates_only_its_dialog_and_group_activity_is_separate(live):
    owner,_,_=live
    owner._lid_to_phone[LID],owner._phone_to_lid[PN]=PN,LID
    view,text=dialog(owner,jid=LID)
    other,other_text=dialog(owner,jid='789@s.whatsapp.net')
    owner.on_presence_update(LID,{LID:{'lastKnownPresence':'recording','isOnline':False}},refresh_offline=False)
    assert 'recording_indicator' in text.text and other_text.writes==1
    writes=text.writes
    owner.on_presence_update('123-456@g.us',{LID:{'lastKnownPresence':'composing'}})
    assert text.writes==writes and 'recording_indicator' in text.text


def test_connection_invalidation_clears_open_activity_without_focus(live):
    owner,_,_=live
    owner.on_presence_update(PN,{PN:{'lastKnownPresence':'composing','isOnline':False}})
    view,text=dialog(owner)
    ContactPresenceMixin._invalidate_contact_presence(owner)
    assert 'typing_indicator' not in text.text
    assert text.focuses==text.events==1 and not owner._presence_timers


def test_destroyed_old_dialog_and_its_delayed_profile_cannot_write_to_new_view(live):
    owner,clock,timers=live
    owner.on_presence_update(PN,{PN:{'lastKnownPresence':'composing','isOnline':False}})
    old,old_text=dialog(owner)
    old_view=old._personal_presence_view
    event=SimpleNamespace(GetEventObject=lambda:old,Skip=lambda:None)
    ConversationDataDialog._on_window_destroy(old,event)
    new,new_text=dialog(owner)
    ConversationDataDialog._populate_personal(old,{})  # delayed worker callback
    old_view.refresh()  # already queued obsolete view work
    clock[0]=110
    timers[-1]()
    assert old_text.writes==1 and 'typing_indicator' in old_text.text
    assert 'typing_indicator' not in new_text.text
    assert len(owner._personal_presence_views)==1 and new_text.focuses==1


def test_child_destroy_does_not_unsubscribe_the_open_dialog(live):
    owner,_,_=live
    view,text=dialog(owner)
    event=SimpleNamespace(GetEventObject=lambda:object(),Skip=lambda:None)
    ConversationDataDialog._on_window_destroy(view,event)
    assert not view._closed.is_set()
    owner.on_presence_update(PN,{PN:{'lastKnownPresence':'composing','isOnline':False}})
    assert 'typing_indicator' in text.text and text.focuses==1


def test_repopulating_replaces_observer_and_does_not_keep_obsolete_profile_text(live):
    owner,_,_=live
    view,text=dialog(owner)
    previous=view._personal_presence_view
    ConversationDataDialog._populate_personal_unsafe(view,{'aboutText':'Updated biography'})
    assert not previous.active and len(owner._personal_presence_views)==1
    owner.on_presence_update(PN,{PN:{'lastKnownPresence':'recording','isOnline':False}})
    assert 'Updated biography' in text.text and 'Biography 📝' not in text.text
    assert text.focuses==2 and text.events==2


def test_weak_observers_do_not_keep_a_discarded_dialog_view_alive(live):
    import gc
    import weakref
    owner,_,_=live
    view,text=dialog(owner)
    ref=weakref.ref(view._personal_presence_view)
    del view
    gc.collect()
    assert ref() is None and not owner._personal_presence_views


def test_shutdown_stops_view_before_reading_or_writing_a_control(live):
    from ui.dialogs.personal_presence import notify_personal_presence
    owner,_,_=live
    view,text=dialog(owner)
    owner._shutting_down=True
    text.ChangeValue=lambda *_:pytest.fail('shutdown touched a control')
    notify_personal_presence(owner)
    assert not owner._personal_presence_views and text.writes==1


@pytest.mark.parametrize('online',[True,False])
def test_expired_activity_reveals_only_separately_observed_online(live,online):
    owner,clock,timers=live
    owner.on_presence_update(PN,{PN:{'lastKnownPresence':'recording','isOnline':online}})
    view,text=dialog(owner)
    clock[0]=110
    timers[-1]()
    assert 'recording_indicator' not in text.text
    assert ('Online' in text.text) is online


@pytest.mark.parametrize('reverse',[False,True])
def test_selection_restore_also_supports_a_port_exposing_the_first_end_as_caret(live,reverse):
    owner,clock,timers=live
    owner.on_presence_update(PN,{PN:{'lastKnownPresence':'composing','isOnline':False}})
    view,text=dialog(owner,windows=True)
    def select(start,end):
        text.selection=(min(start,end),max(start,end))
        text.caret=start
    text.SetSelection=select
    start=text.at('chat_encryption_notice')
    text.SetSelection(start+3,start) if reverse else text.SetSelection(start,start+3)
    old_caret=text.caret
    removed=text.at('chat_encryption_label')-text.at('typing_indicator')
    clock[0]=110
    timers[-1]()
    assert text.selection==(start-removed,start+3-removed)
    assert text.caret==old_caret-removed and text.focuses==1


@pytest.mark.parametrize('before',[[],['Profile 🧑','About 📝']])
def test_native_span_handles_a_presence_line_at_the_end_of_the_text(live,before):
    from ui.dialogs.personal_presence import track_personal_presence
    owner,_,_=live
    owner.on_presence_update(PN,{PN:{'lastKnownPresence':'composing','isOnline':False}})
    text=Text(windows=True)
    text.SetValue('\n'.join([*before,'typing_indicator']))
    view=SimpleNamespace(_mw=owner,_i18n=owner.i18n,_jid=PN,_closed=threading.Event(),_info_ctrl=text)
    track_personal_presence(view,before,[],'typing_indicator')
    text.SetSelection(text.GetLastPosition(),text.GetLastPosition())
    owner.on_presence_update(PN,{PN:{'lastKnownPresence':'paused','isOnline':False}})
    assert text.text=='\n'.join(before)
    assert text.caret==text.GetLastPosition() and text.selection==(text.caret,text.caret)


@pytest.mark.parametrize('state,label',[('composing','typing_indicator'),('recording','recording_indicator')])
@pytest.mark.parametrize('during',['value','focus','already_delivered_expiry'])
def test_initial_native_fill_crossing_expiry_cannot_leave_untracked_activity(live,state,label,during):
    owner,clock,timers=live
    owner.on_presence_update(PN,{PN:{'lastKnownPresence':state,'isOnline':False}})
    text=Text(windows=True)
    rendered=[]
    initial_value,initial_focus=text.SetValue,text.SetFocus
    def write(value):
        rendered.append(value)
        initial_value(value)
        if during=='value':
            clock[0]=110
    def focus():
        initial_focus()
        if during!='value':
            clock[0]=110
        if during=='already_delivered_expiry':
            timers[-1]()  # Native dispatch completed expiry before registration.
    text.SetValue,text.SetFocus=write,focus
    view=SimpleNamespace(_mw=owner,_i18n=owner.i18n,_jid=PN,_name='Contact',
                         _closed=threading.Event(),_info_ctrl=text)
    ConversationDataDialog._populate_personal_unsafe(view,{})
    assert label in rendered[0]
    timers[-1]()
    assert label not in text.text and text.events==text.focuses==1
