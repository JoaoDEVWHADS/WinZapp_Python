"""Inline transcriptions waiting for the one under way, run one after another.

With "Transcribe without the progress window" on, one run at a time is kept on
the main window (`MainWindow._background_transcription`,
ui/transcription_flow.py). Pressing the inline key (Alt+Shift+N, or whichever
key is set to put the text in the message's line) on a second message used to
be refused with "another transcription is still running". An inline result
opens no window, so two of them can never fight over the screen: the second
one now waits here and starts when the first ends.

A transcription that ends in a window (Alt+Shift+T) is still refused while
another runs, since its window would open over whatever the user is doing when
the queue reaches it. So is an inline one whose text would not be kept (the
saved transcriptions turned off for the model): its result opens the window
instead (ui/transcription_flow.py `_report`).

Rules:

* **One entry per message.** Asking again for a waiting message takes it out of
  the queue, as asking again for the running one cancels it.
* **Bounded.** At most `MAX_WAITING`; past that the request is refused like
  before, rather than queued without end.
* **Emptied at shutdown** (MainWindow.stop_transcription_runs()), so the run
  cancelled there does not start the next one.
* **Emptied by a failure that is not about one message** (`ends_the_queue()`):
  no model, a card that refused, a broken component. Every waiting run would
  stop the same way, each with its own question or window.

Entries are the flows themselves; all that is asked of one is
`targets(other)`. No wx, so it is tested directly.
"""

from core.transcription import errors

MAX_WAITING = 50

#: Failures about the one message that was being transcribed: the queue goes on.
_MESSAGE_FAILURES = frozenset({
    errors.CANCELLED, errors.MEDIA_NOT_DOWNLOADED, errors.UNSUPPORTED_AUDIO_FORMAT,
    errors.NO_AUDIO_TRACK, errors.AUDIO_INCOMPLETE,
})


def ends_the_queue(error_code) -> bool:
    """Whether a run that ended with *error_code* (None: it worked) empties
    the queue: any failure but one about its own message."""
    return error_code is not None and error_code not in _MESSAGE_FAILURES


class WaitingRuns:
    """The flows waiting, oldest first. Used on the wx thread only."""

    def __init__(self):
        self._flows = []

    def __len__(self):
        return len(self._flows)

    def add(self, flow) -> int:
        """Queue *flow* and answer its position (1 = next), or 0 when the queue
        is full and nothing was added."""
        if len(self._flows) >= MAX_WAITING:
            return 0
        self._flows.append(flow)
        return len(self._flows)

    def withdraw(self, flow) -> bool:
        """Take out the waiting entry for the same message as *flow*; whether
        there was one."""
        for index, waiting in enumerate(self._flows):
            if waiting.targets(flow):
                del self._flows[index]
                return True
        return False

    def next(self):
        """The oldest waiting flow, taken out of the queue; None when empty."""
        return self._flows.pop(0) if self._flows else None

    def clear(self) -> None:
        self._flows.clear()


def of(main_window) -> WaitingRuns:
    """The main window's queue, made on first use."""
    queue = getattr(main_window, "_waiting_transcriptions", None)
    if not isinstance(queue, WaitingRuns):
        queue = WaitingRuns()
        main_window._waiting_transcriptions = queue
    return queue
