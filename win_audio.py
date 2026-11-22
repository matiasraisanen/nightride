# Finds the player's own audio session on Windows, and reads its level from the session's peak meter.
# That is the same meter the Windows volume mixer shows for each app.
import os
from ctypes import HRESULT, POINTER, c_float
from ctypes.wintypes import DWORD, UINT

import comtypes
from comtypes import COMMETHOD, GUID, IUnknown
from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume

# AudioSessionState: the session is playing sound
SESSION_ACTIVE = 1


class IAudioMeterInformation(IUnknown):
    # pycaw has this interface with only its first method, and we need the peaks per channel.
    # The methods must be in the same order as in Windows' endpointvolume.h.
    _iid_ = GUID("{C02216F6-8C67-4B5B-9D00-D008E73E0064}")
    _methods_ = (
        COMMETHOD([], HRESULT, "GetPeakValue", (["out"], POINTER(c_float), "pfPeak")),
        COMMETHOD([], HRESULT, "GetMeteringChannelCount", (["out"], POINTER(UINT), "pnChannelCount")),
        COMMETHOD(
            [],
            HRESULT,
            "GetChannelsPeakValues",
            (["in"], UINT, "u32ChannelCount"),
            (["in"], POINTER(c_float), "afPeakValues"),
        ),
        COMMETHOD([], HRESULT, "QueryHardwareSupport", (["out"], POINTER(DWORD), "pdwHardwareSupportMask")),
    )


def init_thread():
    # Every thread that uses these must call this first
    comtypes.CoInitialize()


class Session:
    def __init__(self, session):
        # pycaw doesn't offer the meter, so ask the session control for it directly
        self.meter = session._ctl.QueryInterface(IAudioMeterInformation)
        self.volume = session._ctl.QueryInterface(ISimpleAudioVolume)
        self.channels = 0
        self.values = (c_float * 1)()

    def peaks(self):
        # [left, right] highest sample values (0 to 1) of the sound playing right now, before the
        # session's volume is applied. Mono is shown on both sides, and only the first two channels
        # of surround sound are used.
        # The channel count is asked every time: it is 0 until VLC starts playing, and can change when
        # VLC opens its output again. Asking for the wrong number of channels is an error.
        channels = self.meter.GetMeteringChannelCount()
        if channels == 0:
            return [0.0, 0.0]
        if channels != self.channels:
            self.channels = channels
            self.values = (c_float * channels)()
        self.meter.GetChannelsPeakValues(channels, self.values)
        values = list(self.values)
        return values[:2] if len(values) >= 2 else values * 2

    def volume_setting(self):
        # (the session's volume from 0 to 1, whether it is muted)
        return self.volume.GetMasterVolume(), bool(self.volume.GetMute())

    def silenced(self):
        # Whether the session is muted or at zero volume. The meter measures the sound before the
        # volume is applied, so it would otherwise keep moving while nothing is heard.
        volume, muted = self.volume_setting()
        return muted or volume <= 0


def find_own_session():
    # This process's audio session on the default output device, or None if it has none.
    # Prefers the one playing sound, in case there are old ones around.
    pid = os.getpid()
    sessions = [s for s in AudioUtilities.GetAllSessions() if s.ProcessId == pid]
    if not sessions:
        return None
    active = [s for s in sessions if s.State == SESSION_ACTIVE]
    return Session((active or sessions)[0])
