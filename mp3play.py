#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations


class PlaysoundException(Exception):
    pass


def playsound(sound, block=True):
    if not block:
        raise NotImplementedError("block=False cannot be used on this platform yet")
    import os
    from urllib.request import pathname2url

    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    Gst.init(None)
    playbin = Gst.ElementFactory.make("playbin", "playbin")
    if sound.startswith(("http://", "https://")):
        playbin.props.uri = sound
    else:
        playbin.props.uri = "file://" + pathname2url(os.path.abspath(sound))
    set_result = playbin.set_state(Gst.State.PLAYING)
    if set_result != Gst.StateChangeReturn.ASYNC:
        raise PlaysoundException("playbin.set_state returned " + repr(set_result))
    bus = playbin.get_bus()
    bus.poll(Gst.MessageType.EOS, Gst.CLOCK_TIME_NONE)
    playbin.set_state(Gst.State.NULL)


if __name__ == "__main__":
    import sys

    fn = sys.argv[1]
    playsound(fn)
