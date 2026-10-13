# SPDX-License-Identifier: GPL-3.0-or-later
"""Receive-only S1G OFDM receiver for single-stream BCC PPDUs.

The 2 MHz synchronization, pilot, and coding algorithms are adapted from
Daniel Estévez's MIT-licensed IEEE 802.11ah analysis notebook. See
THIRD_PARTY_NOTICES.md. The wider channel receiver and integration are new.

Only frames with a valid IEEE 802.11 FCS are returned. The caller must not
interpret an empty result as evidence that a channel is idle.
"""

from __future__ import annotations

import binascii
from dataclasses import dataclass
from fractions import Fraction
from math import lcm

import numpy as np
from scipy.signal import find_peaks, resample_poly

try:
    from . import _fec
except ImportError:
    _fec = None


_LTF_LEFT = np.array([
    1, 1, -1, -1, 1, 1, -1, 1, -1, 1, 1, 1, 1, 1, 1, -1, -1, 1, 1,
    -1, 1, -1, 1, 1, 1, 1,
])
_LTF_RIGHT = np.array([
    1, -1, -1, 1, 1, -1, 1, -1, 1, -1, -1, -1, -1, -1, 1, 1, -1,
    -1, 1, -1, 1, -1, 1, 1, 1, 1,
])
_LTF = np.concatenate(([1, 1], _LTF_LEFT, _LTF_RIGHT, [-1, -1]))
# 32-point S1G_1M LTF, in FFT-shifted subcarrier order. The 1 MHz
# preamble has four LTF symbols and six repeated-code SIG symbols.
_LTF_1 = np.array([
    0,0,0,1,-1,1,-1,-1,1,-1,1,1,-1,1,1,1,
    0,-1,-1,-1,1,-1,-1,-1,1,-1,1,1,1,-1,0,0,
])
_LTF_1_TIME = np.fft.ifft(np.fft.ifftshift(_LTF_1))*32
_DATA_1 = np.array([k for k in range(-13,14) if k not in (0,-7,7)])
# VHT/S1G 256-point LTF tones between the four duplicated 2 MHz regions.
# These tones are occupied in the data field. Inferring their channel from
# adjacent 2 MHz tones can invert or amplify high-order QAM bits.
_LTF_8_EXTRA = {
    -96:1,-67:-1,-66:1,-65:1,-64:-1,-63:1,-62:-1,-61:1,
    -32:1,-3:1,-2:-1,2:1,3:-1,32:1,
    61:-1,62:1,63:1,64:-1,65:1,66:-1,67:1,96:1,
}
_SIG_1_PERM = np.array([0,3,6,9,12,15,18,21,1,4,7,10,13,16,19,22,2,5,8,11,14,17,20,23])
_SIG_1_REPEAT = np.array([1,0,0,0,0,1,0,1,0,1,1,1])
_SUB56 = np.array([k for k in range(-28, 29) if k])
_STF = np.array([
    0, 0, 1+1j, 0, 0, 0, -1-1j, 0, 0, 0, 1+1j, 0, 0, 0,
    -1-1j, 0, 0, 0, -1-1j, 0, 0, 0, 1+1j, 0, 0, 0, 0, 0,
    0, 0, -1-1j, 0, 0, 0, -1-1j, 0, 0, 0, 1+1j, 0, 0, 0,
    1+1j, 0, 0, 0, 1+1j, 0, 0, 0, 1+1j, 0, 0,
]) / np.sqrt(2)
_PILOT_PSI = np.array([1, 1, 1, -1])
_PILOT_POLARITY = np.array([
    1,1,1,1, -1,-1,-1,1, -1,-1,-1,-1, 1,1,-1,1, -1,-1,1,1, -1,1,1,-1, 1,1,1,1, 1,1,-1,1,
    1,1,-1,1, 1,-1,-1,1, 1,1,-1,1, -1,-1,-1,1, -1,1,-1,-1, 1,-1,-1,1, 1,1,1,1, -1,-1,1,1,
    -1,-1,1,-1, 1,-1,1,1, -1,-1,-1,1, 1,-1,-1,-1, -1,1,-1,-1, 1,-1,1,1, 1,1,-1,1, -1,1,-1,1,
    -1,-1,-1,-1, -1,1,-1,1, 1,-1,1,-1, 1,1,1,-1, -1,1,-1,-1, -1,1,1,1, -1,-1,-1,-1, -1,-1,-1])
_TRAVELING_2 = np.array([
    [-28,-24,-20,-16,-26,-22,-18,-27,-23,-19,-15,-25,-21,-17],
    [-12,-8,-4,-2,-14,-10,-6,-11,-7,-3,1,-13,-9,-5],
    [4,8,12,16,2,6,10,5,9,13,17,-1,3,7],
    [20,24,28,26,14,18,22,21,25,23,27,11,15,19],
]).T

_MCS = {
    0: ("BPSK", 1, 2), 1: ("QPSK", 1, 2), 2: ("QPSK", 3, 4),
    3: ("16QAM", 1, 2), 4: ("16QAM", 3, 4),
    5: ("64QAM", 2, 3), 6: ("64QAM", 3, 4),
    7: ("64QAM", 5, 6), 8: ("256QAM", 3, 4),
    9: ("256QAM", 5, 6),
}


class PhyReject(ValueError):
    """A candidate did not meet the supported S1G or FCS contract."""


@dataclass(frozen=True)
class RecoveredFrame:
    mpdu: bytes
    sample_offset: int
    bandwidth_mhz: int
    mcs: int
    ppdu_format: str
    short_gi: bool
    cfo_hz: float
    fcs_ok: bool = True


def _crc4(bits):
    reg = 0xf
    for bit in bits:
        reg = ((reg << 1) ^ (0x3 if bit ^ (reg >> 3) else 0)) & 0xf
    return reg ^ 0xf


def _crc8(bits):
    reg = 0xff
    for bit in bits:
        reg = ((reg << 1) ^ (0x7 if bit ^ (reg >> 7) else 0)) & 0xff
    return reg ^ 0xff


def _fcs_ok(frame):
    return len(frame) >= 4 and (binascii.crc32(frame[:-4]) & 0xffffffff) == int.from_bytes(frame[-4:], "little")


def _viterbi(soft, end_state=0):
    """K=7 rate-1/2 soft Viterbi with bounded O(64*n) memory."""
    soft = np.asarray(soft, dtype=float).reshape(-1, 2)
    if _fec is not None and end_state == 0:
        packed = np.ascontiguousarray(soft, dtype=np.float32)
        return np.frombuffer(_fec.decode(packed), dtype=np.uint8)
    if len(soft) > 1200000:
        raise PhyReject("Viterbi input exceeds bounded step range")
    states = np.arange(64)
    predecessor = np.stack((2 * (states & 31), 2 * (states & 31) + 1), axis=1)
    bit = states >> 5
    p = predecessor
    out0 = (bit[:, None] ^ p ^ (p >> 1) ^ (p >> 3) ^ (p >> 4)) & 1
    out1 = (bit[:, None] ^ p ^ (p >> 3) ^ (p >> 4) ^ (p >> 5)) & 1
    sign0, sign1 = 2 * out0 - 1, 2 * out1 - 1
    metrics = np.full(64, np.inf)
    metrics[0] = 0
    decisions = np.empty((len(soft), 64), dtype=np.uint8)
    for t, (y0, y1) in enumerate(soft):
        candidates = metrics[p] - (sign0 * y0 + sign1 * y1)
        choice = np.argmin(candidates, axis=1)
        decisions[t] = choice
        metrics = candidates[states, choice]
    bits = np.empty(len(soft), dtype=np.uint8)
    state = end_state
    for t in range(len(soft) - 1, -1, -1):
        bits[t] = state >> 5
        state = int(predecessor[state, decisions[t, state]])
    return bits


def _descramble(bits):
    reg = 0
    out = np.empty_like(bits)
    for j, bit in enumerate(bits):
        feedback = int(bit) if j < 7 else ((reg >> 3) ^ (reg >> 6)) & 1
        out[j] = bit ^ feedback
        reg = ((reg << 1) | feedback) & 0x7f
    return out


def _deinterleave(soft, n_data, bits_per_tone, width):
    ncbps = n_data * bits_per_tone
    ncol = {1: 8, 2: 13, 4: 18, 8: 26}[width]
    if ncbps % ncol:
        raise PhyReject("invalid interleaver shape")
    nrow = ncbps // ncol
    k = np.arange(ncbps)
    s = max(1, bits_per_tone // 2)
    if width == 1:
        first = s*(k//s)+((k+(ncol*k)//ncbps)%s)
        second = ncol*k-(ncbps-1)*(k//nrow)
        result = np.empty_like(soft.reshape(-1,ncbps))
        result[:,second[first]] = soft.reshape(-1,ncbps)
        return result.ravel()
    second = s * (k // s) + ((k + ncbps - (ncol * k) // ncbps) % s)
    first = nrow * (k % ncol) + k // ncol
    return soft.reshape(-1, ncbps)[:, second][:, first].ravel()


def _depuncture(soft, rate):
    # The soft input is positive for a transmitted one after demapping.
    if rate == (1, 2):
        return soft.reshape(-1, 2)
    if rate == (3, 4):
        inbits = soft.reshape(-1, 4)
        out = np.zeros((len(inbits), 3, 2))
        out[:, 0] = inbits[:, :2]
        out[:, 1, 0] = inbits[:, 2]
        out[:, 2, 1] = inbits[:, 3]
    elif rate == (2, 3):
        inbits = soft.reshape(-1, 3)
        out = np.zeros((len(inbits), 2, 2))
        out[:, 0] = inbits[:, :2]
        out[:, 1, 0] = inbits[:, 2]
    elif rate == (5, 6):
        inbits = soft.reshape(-1, 6)
        out = np.zeros((len(inbits), 5, 2))
        out[:, 0] = inbits[:, :2]
        out[:, 1, 0] = inbits[:, 2]
        out[:, 2, 1] = inbits[:, 3]
        out[:, 3, 0] = inbits[:, 4]
        out[:, 4, 1] = inbits[:, 5]
    else:
        raise PhyReject("unsupported coding rate")
    return out.reshape(-1, 2)


def _constellation(name):
    if name == "BPSK":
        return np.array([-1, 1], dtype=complex)
    if name == "QPSK":
        return np.array([-1-1j, -1+1j, 1-1j, 1+1j]) / np.sqrt(2)
    order = {"16QAM": 4, "64QAM": 8, "256QAM": 16}[name]
    levels = np.arange(-(order - 1), order, 2)
    scale = np.sqrt(2 * (order * order - 1) / 3)
    points = []
    for code in range(order * order):
        i_gray = code >> (order.bit_length() - 1)
        q_gray = code & (order - 1)
        def ungray(value):
            result = value
            while value:
                value >>= 1
                result ^= value
            return result
        points.append((levels[ungray(i_gray)] + 1j * levels[ungray(q_gray)]) / scale)
    return np.asarray(points)


def _soft_demap(symbols, name):
    const = _constellation(name)
    nbits = int(np.log2(len(const)))
    distance = abs(symbols.ravel()[:, None] - const[None, :]) ** 2
    # Max-log LLR: positive means bit 1 was more likely. Scale does not
    # affect Viterbi decisions within one PPDU.
    out = np.empty((len(distance), nbits))
    for bit in range(nbits):
        zero = ((np.arange(len(const)) >> (nbits - bit - 1)) & 1) == 0
        out[:, bit] = distance[:, zero].min(axis=1) - distance[:, ~zero].min(axis=1)
    return out.ravel()


def _parse_sig(bits, width, long_format=False):
    if len(bits) != 48 or _crc4(bits[:38]) != sum(int(bits[i]) << (41-i) for i in range(38, 42)):
        raise PhyReject("SIG CRC")
    if np.any(bits[42:48]):
        raise PhyReject("SIG BCC tail")
    bandwidth_code = sum(int(bits[i]) << (i-3) for i in range(3, 5))
    if bandwidth_code != {2: 0, 4: 1, 8: 2}[width]:
        raise PhyReject("SIG bandwidth mismatch")
    if bits[1] or bits[5] or bits[6] or bits[17]:
        raise PhyReject("STBC, multiple streams, or LDPC unsupported")
    if long_format:
        if bits[0] or not bits[36]:
            raise PhyReject("S1G_LONG MU or invalid fixed SIG bit")
    elif not bits[0] or bits[37]:
        raise PhyReject("invalid S1G_SHORT or NDP SIG")
    mcs = sum(int(bits[i]) << (i-19) for i in range(19, 23))
    if mcs not in _MCS:
        raise PhyReject("unsupported MCS")
    if width>2 and (bits[37] if long_format else bits[36]):
        raise PhyReject("wide-channel traveling pilots unsupported")
    aggregation = bool(bits[24])
    length = sum(int(bits[i]) << (i-25) for i in range(25, 34))
    if length > 4095:
        raise PhyReject("excessive length")
    return {
        "mcs": mcs, "length": length, "aggregation": aggregation,
        "short_gi": bool(bits[16]), "traveling_pilots": bool(bits[37] if long_format else bits[36]),
        "ppdu_format": "S1G_LONG" if long_format else "S1G_SHORT", "coding": "BCC",
    }


def _fft_symbol(x, start, cfo, nfft, cp_correction):
    if start < 0 or start + nfft > len(x):
        raise PhyReject("truncated symbol")
    samples = x[start:start+nfft] * np.exp(-1j * cfo * np.arange(start, start+nfft))
    correction = np.exp(1j * 2 * np.pi * cp_correction * np.fft.fftshift(np.fft.fftfreq(nfft)))
    return np.fft.fftshift(np.fft.fft(samples)) * correction


def _preamble_2(x, start):
    """Decode the 2 MHz duplicated preamble from a 4 Msps channelized stream."""
    tu, cp, ts, dc = 128, 32, 160, 64
    if start < 0 or start + 6*ts > len(x):
        raise PhyReject("truncated preamble")
    y = x[start:start+2*ts]
    coarse = np.angle(np.sum(y[cp:] * np.conj(y[:-cp]))) / cp
    corrected = y * np.exp(-1j * coarse * np.arange(len(y)))
    fine = np.angle(np.sum(corrected[ts:] * np.conj(corrected[:-ts]))) / ts
    cfo = coarse + fine

    # Use the comb-like STF to refine the start sample before LTF/SIG FFTs.
    stf = np.array([
        _fft_symbol(x, start+cp//2+j*ts, cfo, tu, -cp//2)
        for j in range(2)
    ])[:, dc-26:dc+27] * np.conj(_STF)
    active_stf = _STF != 0
    stf_avg = stf[:, active_stf].sum(axis=0)
    with_dc = np.zeros(len(stf_avg)+1, complex)
    half = len(stf_avg)//2
    with_dc[:half], with_dc[-half:] = stf_avg[:half], stf_avg[-half:]
    fft = abs(np.fft.fft(with_dc))
    ix = int(np.argmax(fft))
    if ix >= len(fft)//2:
        ix -= len(fft)
    coarse_sto = -ix * tu / (4 * len(fft))
    stf_bins = np.arange(-26, 27)[active_stf]
    stf_removed = stf_avg * np.exp(1j*2*np.pi*coarse_sto*stf_bins/tu)
    average_phase = np.angle(np.mean(stf_removed))
    fine_sto = -np.polyfit(stf_bins, np.angle(stf_removed*np.exp(-1j*average_phase)), 1)[0]*tu/(2*np.pi)
    sto = coarse_sto + fine_sto
    start += round(sto)
    sto -= round(sto)
    if start < 0 or start + 6*ts > len(x):
        raise PhyReject("timing outside capture")

    h = np.empty(tu, complex)
    h[:] = np.nan
    ltf = np.array([
        _fft_symbol(x, start+(2+j)*ts+(2*cp-cp//2 if j==0 else cp//2), cfo, tu, cp//2+sto)
        for j in range(2)
    ])
    ltf_pair=ltf[:,_SUB56+dc]
    coherence=abs(np.vdot(ltf_pair[0],ltf_pair[1]))/max(
        np.linalg.norm(ltf_pair[0])*np.linalg.norm(ltf_pair[1]),1e-9)
    if coherence<.7:
        raise PhyReject("LTF pair is incoherent")
    h[_SUB56+dc] = (ltf[:, _SUB56+dc]*_LTF).mean(axis=0)
    sig = np.array([
        _fft_symbol(x, start+(4+j)*ts+cp//2, cfo, tu, cp//2+sto)
        for j in range(2)
    ])
    sig_bins = np.array([k for k in range(-26, 27) if k and k not in (-21,-7,7,21)])
    sig_eq = sig[:, sig_bins+dc] / h[sig_bins+dc]
    long_format = np.sum(sig_eq[1].real**2) > np.sum(sig_eq[1].imag**2)
    sig_syms = np.concatenate((sig_eq[0].imag, sig_eq[1].real if long_format else sig_eq[1].imag))
    ncbps = 48
    k = np.arange(ncbps)
    permutation = (ncbps//16)*(k%16)+k//16
    deinterleaved = sig_syms.reshape(2, ncbps)[:, permutation].ravel()
    bits = _viterbi(deinterleaved.reshape(-1, 2))
    return start, sto, cfo, h, bits, long_format


def _unpack_mpdu(bits, sig):
    if len(bits) < 8 or np.any(bits[:7]):
        raise PhyReject("SERVICE bits")
    payload = bits[8:]
    if sig["aggregation"]:
        frames = []
        while len(payload) >= 32:
            delimiter = payload[:32]
            length = sum(int(delimiter[i]) << (i-4) for i in range(4, 16)) + 4096*(int(delimiter[2])+2*int(delimiter[3]))
            if delimiter[1] or _crc8(delimiter[:16]) != int(np.packbits(delimiter[16:24])[0]) or bytes(np.packbits(delimiter[24:32][::-1])) != b"N":
                if frames:
                    break  # Preserve earlier members that passed their own FCS.
                raise PhyReject("A-MPDU delimiter")
            if 32+8*length > len(payload):
                if frames:
                    break
                raise PhyReject("truncated A-MPDU")
            frame = bytes(np.packbits(payload[32:32+8*length].reshape(-1, 8)[:, ::-1]))
            if _fcs_ok(frame):
                frames.append(frame)
            payload = payload[((32+8*length+31)//32)*32:]
            if delimiter[0]:
                break
        return frames
    length = sig["length"]
    if len(payload) < length*8:
        raise PhyReject("truncated PSDU")
    frame = bytes(np.packbits(payload[:length*8].reshape(-1, 8)[:, ::-1]))
    # Some transmitters round the advertised length to a 4-byte boundary.
    return [frame[:len(frame)-pad] for pad in range(4) if _fcs_ok(frame[:len(frame)-pad])]


def _payload_2(x, start, sto, cfo, h, sig, phase_mode="fit"):
    tu, cp, ts, dc = 128, 32, 160, 64
    modulation, num, den = _MCS[sig["mcs"]]
    bits_per_tone = int(np.log2(len(_constellation(modulation))))
    ndbps = 52*bits_per_tone*num//den
    count = sig["length"] if sig["aggregation"] else (8*sig["length"]+8+6+ndbps-1)//ndbps
    if not 0 < count <= 4095:
        raise PhyReject("invalid symbol count")
    pilot_bins = np.array([-21,-7,7,21])
    all_bins = _SUB56
    phase_fit = np.zeros(2)
    equalized = []
    pilot_errors = []
    position = start+6*ts
    if sig["ppdu_format"] == "S1G_LONG":
        # In single-user S1G_LONG, D-STF precedes D-LTF1 and SIG-B;
        # SIG-B repeats D-LTF1. The beam-changeable data portion needs its
        # own channel estimate rather than the omnidirectional LTF1 estimate.
        dltf = np.array([
            _fft_symbol(x, position+(j+1)*ts+cp//2, cfo, tu, cp//2+sto)
            for j in range(2)
        ])
        h = h.copy()
        h[_SUB56+dc] = (dltf[:, _SUB56+dc]*_LTF).mean(axis=0)
        if np.any(abs(h[_SUB56+dc])<1e-9):
            raise PhyReject("invalid S1G_LONG beam channel estimate")
        position += 3*ts
    for j in range(count):
        gi = cp//2 if sig["short_gi"] and j else cp
        cp_offset = gi//2
        fft = _fft_symbol(x, position+cp_offset, cfo, tu, cp_offset+sto)
        position += tu+gi
        values = np.zeros_like(fft)
        values[_SUB56+dc] = fft[_SUB56+dc] / h[_SUB56+dc]
        pb = _TRAVELING_2[j%14] if sig["traveling_pilots"] else pilot_bins
        pilot_values = values[pb+dc]*np.roll(_PILOT_PSI,-j)*_PILOT_POLARITY[(j+2)%len(_PILOT_POLARITY)]
        if phase_mode == "fit":
            phase_fit = np.polyfit(pb, np.angle(pilot_values*np.exp(-1j*np.polyval(phase_fit,pb))), 1)+phase_fit
            correction = np.exp(-1j*np.polyval(phase_fit,np.arange(-dc,dc)))
        elif phase_mode == "common":
            correction = np.full(tu, np.exp(-1j*np.angle(np.sum(pilot_values))))
        else:
            raise ValueError("unknown pilot phase mode")
        pilot_errors.extend(pilot_values*correction[pb+dc])
        data_bins = np.array([k for k in all_bins if k not in pb])
        equalized.extend(values[data_bins+dc]*correction[data_bins+dc])
    equalized = np.asarray(equalized)
    soft = _soft_demap(equalized, modulation)
    decoded = _viterbi(_depuncture(_deinterleave(soft, 52, bits_per_tone, 2), (num,den)))
    return _unpack_mpdu(_descramble(decoded[:-6]), sig)


def _payload_wide(x, start, cfo_hz, sig, width, phase_mode="fit"):
    """Decode a 4/8 MHz one-stream BCC PPDU from full-band complex IQ."""
    tu = width*32
    cp, ts, dc = tu//4, tu+tu//4, tu//2
    centers = {4: (-32,32), 8: (-96,-32,32,96)}[width]
    active = np.array([k for k in range(-{4:58,8:122}[width], {4:59,8:123}[width]) if abs(k)>1])
    pilots = np.array({4:(-53,-25,-11,11,25,53), 8:(-103,-75,-39,-11,11,39,75,103)}[width])
    # The six 4 MHz pilot signs rotate each data symbol. Treating them all
    # as +1 makes their sum approach zero and gives a noisy common-phase
    # estimate, especially over long PPDUs and at higher MCS. The 8 MHz
    # pilot path is kept separate until its sequence is independently checked.
    pilot_psi = np.array((1, 1, 1, -1, -1, 1)) if width == 4 else np.ones(8)
    data_bins = np.array([k for k in active if k not in pilots])
    modulation, num, den = _MCS[sig["mcs"]]
    bits_per_tone = int(np.log2(len(_constellation(modulation))))
    ndbps = len(data_bins)*bits_per_tone*num//den
    count = sig["length"] if sig["aggregation"] else (8*sig["length"]+8+6+ndbps-1)//ndbps
    if not 0 < count <= 4095:
        raise PhyReject("invalid symbol count")
    cfo = cfo_hz*2*np.pi/(width*1e6)
    ltf = np.array([
        _fft_symbol(x, start+(2+j)*ts+(2*cp-cp//2 if j==0 else cp//2), cfo, tu, cp//2)
        for j in range(2)
    ]).mean(axis=0)
    known_bins, channel = [], []
    for center in centers:
        bins = center+_SUB56
        known_bins.extend(bins)
        channel.extend(ltf[bins+dc]/_LTF)
    if width==8:
        for tone,sign in _LTF_8_EXTRA.items():
            known_bins.append(tone)
            channel.append(ltf[tone+dc]/sign)
    order=np.argsort(known_bins)
    known_bins, channel = np.asarray(known_bins)[order], np.asarray(channel)[order]
    h = np.interp(active,known_bins,channel.real)+1j*np.interp(active,known_bins,channel.imag)
    hfull = np.ones(tu,complex)
    hfull[active+dc] = h
    position = start+6*ts
    equalized=[]
    phase_fit = np.zeros(2)
    for j in range(count):
        gi = cp//2 if sig["short_gi"] and j else cp
        # Two samples after the GI midpoint substantially reduces edge noise
        # on the validated 8 MHz HackRF recording. Keep the same physical
        # sample point at narrower widths (one sample at 4 MHz).
        offset = max(1,width//4)
        fft = _fft_symbol(x, position+gi//2+offset, cfo, tu, gi//2-offset)
        position += tu+gi
        eq=fft/hfull
        if width == 4:
            expected = np.roll(pilot_psi,-j)*_PILOT_POLARITY[(j+2)%len(_PILOT_POLARITY)]
            measured = eq[pilots+dc]*expected
            if phase_mode == "fit":
                residual = np.unwrap(np.angle(measured*np.exp(-1j*np.polyval(phase_fit,pilots))))
                phase_fit += np.polyfit(pilots,residual,1)
                correction = np.exp(-1j*np.polyval(phase_fit,data_bins))
            elif phase_mode == "common":
                correction = np.exp(-1j*np.angle(np.sum(measured)))
            else:
                raise ValueError("unknown pilot phase mode")
            equalized.extend(eq[data_bins+dc]*correction)
            continue
        if modulation == "BPSK":
            phase=np.angle(np.sum(eq[data_bins+dc]**2))/2
        else:
            # Pilot-assisted common phase tracking for higher constellations.
            # The pilot signs are validated by FCS before any MPDU is emitted.
            phase=np.angle(np.sum(eq[pilots+dc]*np.roll(pilot_psi,-j)*
                                  _PILOT_POLARITY[(j+2)%len(_PILOT_POLARITY)]))
        equalized.extend(eq[data_bins+dc]*np.exp(-1j*phase))
    soft=_soft_demap(np.asarray(equalized),modulation)
    decoded=_viterbi(_depuncture(_deinterleave(soft,len(data_bins),bits_per_tone,width),(num,den)))
    return _unpack_mpdu(_descramble(decoded[:-6]),sig)


def _parse_sig_1(bits):
    if len(bits)!=36 or np.any(bits[30:]) or _crc4(bits[:26]) != sum(int(bits[j])<<(29-j) for j in range(26,30)):
        raise PhyReject("S1G_1M SIG CRC or tail")
    if bits[0] or bits[1] or bits[3] or bits[5] or bits[25] or bits[24]:
        raise PhyReject("S1G_1M streams, coding, STBC, NDP, or traveling pilots unsupported")
    if not bits[4] or not bits[6]:
        raise PhyReject("S1G_1M reserved SIG bits")
    mcs=sum(int(bits[7+j])<<j for j in range(4))
    if mcs not in range(8) and mcs!=10:
        raise PhyReject("S1G_1M MCS unsupported")
    length=sum(int(bits[12+j])<<j for j in range(9))
    if not 0<length<=511:
        raise PhyReject("S1G_1M length invalid")
    return {"mcs":mcs,"length":length,"aggregation":bool(bits[11]),
            "short_gi":bool(bits[2]),"traveling_pilots":bool(bits[24]),
            "ppdu_format":"S1G_1M","coding":"BCC"}


def _decode_1mhz_candidate(x, start):
    if start<0 or start+384+32>len(x):
        raise PhyReject("truncated S1G_1M")
    cfo=np.angle(np.vdot(x[start:start+32],x[start+32:start+64]))/32
    ltf=np.array([_fft_symbol(x,start+delta,cfo,32,0)
                  for delta in (0,32,72,112)])
    h=np.ones(32,complex)
    active=_LTF_1!=0
    h[active]=(ltf[:,active]/_LTF_1[active]).mean(axis=0)
    if np.any(abs(h[active])<1e-9):
        raise PhyReject("invalid S1G_1M channel estimate")
    sig_syms=[]
    for j in range(6):
        fft=_fft_symbol(x,start+144+j*40+4,cfo,32,4)
        sig_syms.append((fft/h)[_DATA_1+16].real)
    deintl=np.asarray(sig_syms)[:,_SIG_1_PERM]
    soft=(deintl[:,:12]+deintl[:,12:]*(1-2*_SIG_1_REPEAT)).ravel()
    sig=_parse_sig_1(_viterbi(soft))
    modulation,num,den=_MCS[0 if sig["mcs"]==10 else sig["mcs"]]
    n_bpsc=int(np.log2(len(_constellation(modulation))))
    n_dbps=24*n_bpsc*num//den//(2 if sig["mcs"]==10 else 1)
    count=sig["length"] if sig["aggregation"] else (8*sig["length"]+8+6+n_dbps-1)//n_dbps
    if not 0<count<=1024:
        raise PhyReject("S1G_1M symbol count invalid")
    symbols=[]
    position=start+384
    for j in range(count):
        gi=4 if sig["short_gi"] and j else 8
        fft=_fft_symbol(x,position+gi//2,cfo,32,gi//2)
        position+=32+gi
        symbols.append(fft/h)
    for use_pilots in (False,True):
        equalized=[]
        for j,eq in enumerate(symbols):
            if use_pilots:
                polarity=_PILOT_POLARITY[(j+6)%len(_PILOT_POLARITY)]
                expected=polarity*(1 if j%2==0 else -1)
                phase=np.angle(expected*(eq[16-7]-eq[16+7]))
            else:
                phase=0
            equalized.extend(eq[_DATA_1+16]*np.exp(-1j*phase))
        soft=_soft_demap(np.asarray(equalized),modulation)
        if sig["mcs"]==10:
            # S1G_1M MCS10 repeats each 12-bit coded symbol with a
            # defined XOR pattern before 24-tone interleaving.
            deintl=np.asarray(soft).reshape(-1,24)[:,_SIG_1_PERM]
            coded=(deintl[:,:12]+deintl[:,12:]*(1-2*_SIG_1_REPEAT)).ravel()
        else:
            coded=_deinterleave(soft,24,n_bpsc,1)
        decoded=_viterbi(_depuncture(coded,(num,den)))
        frames=_unpack_mpdu(_descramble(decoded[:-6]),sig)
        if frames:
            return frames,sig,cfo*1e6/(2*np.pi)
    return [],sig,cfo*1e6/(2*np.pi)


def _decode_1mhz_window(values,sample_rate,offset_hz,max_candidates,search_duration):
    x=_resample(values,sample_rate,1e6,offset_hz)
    template=_LTF_1_TIME
    corr=abs(np.correlate(x,template,mode="valid"))
    power=np.abs(x)**2
    cs=np.concatenate(([0.],np.cumsum(power,dtype=np.float64)))
    energy=cs[32:]-cs[:-32]
    score=corr/np.sqrt(np.maximum(energy*np.vdot(template,template).real,1e-9))
    search_end=len(score) if search_duration is None else min(len(score),round(search_duration*1e6))
    peaks,_=find_peaks(score[:search_end],height=.55,distance=24)
    candidates=[]
    for peak in peaks:
        if peak+112+32>=len(x):
            continue
        if all(np.max(score[peak+delta-2:peak+delta+3])>.55 for delta in (32,72,112)):
            candidates.append(int(peak))
    frames=[]
    tried=set()
    for peak in sorted(candidates,key=lambda p:score[p],reverse=True)[:max_candidates]:
        for start in range(peak-1,peak+3):
            if start in tried:
                continue
            tried.add(start)
            try:
                mpdus,sig,cfo_hz=_decode_1mhz_candidate(x,start)
                for mpdu in mpdus:
                    frames.append(RecoveredFrame(mpdu,round(start*sample_rate/1e6),1,
                                                  sig["mcs"],"S1G_1M",sig["short_gi"],float(cfo_hz)))
                if mpdus:
                    break
            except (PhyReject,ValueError,IndexError,ZeroDivisionError,FloatingPointError):
                continue
    unique=[]
    for frame in sorted(frames,key=lambda f:f.sample_offset):
        if not any(abs(frame.sample_offset-prior.sample_offset)<round(sample_rate*.0002)
                   and frame.mpdu==prior.mpdu for prior in unique):
            unique.append(frame)
    return unique


def _payload_input_end(refined,sig,width,sample_rate,total_samples):
    modulation,num,den=_MCS[sig["mcs"]]
    bits_per_tone=int(np.log2(len(_constellation(modulation))))
    ndbps={2:52,4:108,8:234}[width]*bits_per_tone*num//den
    count=sig["length"] if sig["aggregation"] else (8*sig["length"]+14+ndbps-1)//ndbps
    if not 0<count<=4095:
        raise PhyReject("invalid symbol count")
    # STF/LTF/SIG occupy six 40-us symbols. Include one extra guard
    # interval and 0.2 ms of filter margin beyond the advertised payload.
    duration=refined/4e6+(6+count+(3 if sig["ppdu_format"]=="S1G_LONG" else 0))*40e-6+0.0002
    return min(total_samples,max(0,round(duration*sample_rate)))


def _resample(samples, sample_rate, output_rate, offset_hz):
    ratio=Fraction(output_rate/sample_rate).limit_denominator(1000)
    actual=sample_rate*ratio.numerator/ratio.denominator
    if abs(actual-output_rate)>output_rate*1e-5:
        raise ValueError("sample rate cannot be represented accurately")
    t=np.arange(len(samples))/sample_rate
    shifted=samples*np.exp(-2j*np.pi*offset_hz*t)
    return resample_poly(shifted,ratio.numerator,ratio.denominator)


def _complex_iq(samples):
    """Convert only the IQ slice currently needed by the receiver."""
    if samples.ndim == 2:
        values = samples.astype(np.float32)
        return values[:, 0]+1j*values[:, 1]
    return samples


_SPECTRAL_TAPER = np.hanning(2048)


def subband_power_fraction(samples, candidate, sample_rate):
    """Largest 2 MHz power share in a short IQ window after a raw candidate.

    Used only to rank or optionally filter 8 MHz preamble candidates. It is
    not a packet-validity test; SIG CRC and MPDU FCS remain mandatory. Return
    None when the window is incomplete so callers can retain the candidate.
    """
    begin = candidate+round(sample_rate*10e-6)
    end = begin+len(_SPECTRAL_TAPER)
    if begin < 0 or end > len(samples):
        return None
    iq = _complex_iq(np.asarray(samples[begin:end]))
    spectrum = np.abs(np.fft.fft(iq*_SPECTRAL_TAPER))**2
    bins = max(1, min(len(spectrum), round(2e6*len(spectrum)/sample_rate)))
    cumulative = np.concatenate(([0.], np.cumsum(spectrum)))
    total = cumulative[-1]
    return float(np.max(cumulative[bins:]-cumulative[:-bins])/total) if total else 0.0


def resample_phase_period(sample_rate, bandwidth_mhz):
    """Input-sample period that preserves every channelizer's output lattice.

    A bounded window beginning at a different input phase can change the
    fractional positions returned by ``resample_poly``. Callers with a known
    absolute sample offset should align window starts to this period before
    decoding; the PHY still requires SIG CRC and MPDU FCS.
    """
    if not np.isfinite(sample_rate) or sample_rate <= 0 or bandwidth_mhz not in (1,2,4,8):
        raise ValueError("invalid sample rate or S1G width")
    rates = [1e6] if bandwidth_mhz == 1 else [4e6]
    if bandwidth_mhz > 2:
        rates.append(bandwidth_mhz*1e6)
    return lcm(*(Fraction(rate/sample_rate).limit_denominator(1000).denominator
                 for rate in rates))


def _candidates(x, threshold=.75):
    # Sliding STF autocorrelation over two long-GI symbols, normalized by
    # instantaneous power. The SIG CRC and MPDU FCS are final discriminators.
    lag=32
    length=2*160-lag
    product=x[lag:]*np.conj(x[:-lag])
    power=(abs(x[lag:])**2+abs(x[:-lag])**2)*.5
    # Prefix sums make detection linear in window size. A direct convolution
    # costs O(window_size * 288) and cannot sustain a wide capture on a Pi.
    product_sum=np.concatenate(([0j],np.cumsum(product,dtype=np.complex128)))
    power_sum=np.concatenate(([0.],np.cumsum(power,dtype=np.float64)))
    corr=product_sum[length:]-product_sum[:-length]
    energy=power_sum[length:]-power_sum[:-length]
    score=abs(corr)/np.maximum(energy,1e-9)
    peaks,_=find_peaks(score,height=threshold,distance=160)
    return sorted(peaks,key=lambda i:score[i],reverse=True),score


def detect_stf_raw(samples, sample_rate, threshold=.75):
    """Find candidate STF starts in raw IQ without channelizing the entire file.

    A sparse read is safe only for detection: it aliases the channel and can
    also respond to other periodic OFDM signals. Full-rate SIG and FCS
    decoding remains mandatory before publishing an MPDU.
    """
    if sample_rate < 2e6:
        raise ValueError("raw STF detector needs at least 2 Msps")
    values=np.asarray(samples)
    if values.ndim==2 and values.shape[1]==2:
        if values.dtype==np.uint8:
            values=values.view(np.int8)
        values=values.astype(np.float32)
        values=values[:,0]+1j*values[:,1]
    if values.ndim!=1 or not np.iscomplexobj(values):
        raise ValueError("samples must be complex IQ or Nx2 I/Q")
    stride=max(1,int(sample_rate/1.25e6))
    sparse=values[::stride]
    sparse=sparse-np.mean(sparse)
    rate=sample_rate/stride
    lag=round(rate*8e-6)
    length=round(rate*72e-6)
    if len(sparse)<length+lag+1:
        return []
    product=sparse[lag:]*np.conj(sparse[:-lag])
    power=(abs(sparse[lag:])**2+abs(sparse[:-lag])**2)*.5
    summed=np.concatenate(([0j],np.cumsum(product,dtype=np.complex128)))
    energy=np.concatenate(([0.],np.cumsum(power,dtype=np.float64)))
    score=abs(summed[length:]-summed[:-length])/np.maximum(energy[length:]-energy[:-length],1e-9)
    peaks,_=find_peaks(score,height=threshold,distance=max(1,round(rate*0.00015)))
    return [int(k*stride) for k in peaks]


def decode_iq_window(samples, sample_rate, bandwidth_mhz, offset_hz=0,
                     max_candidates=32, search_duration=None,
                     candidate_hint=None):
    """Decode FCS-checked single-stream BCC MPDUs from bounded complex IQ.

    ``samples`` may be complex64/complex128 or Nx2 signed-byte I/Q. The input
    window should include at least 0.5 ms before each candidate PPDU. Long
    recordings should be fed as overlapping bounded windows.
    """
    if not np.isfinite(sample_rate) or sample_rate<=0 or not np.isfinite(offset_hz):
        raise ValueError("sample rate and offset must be finite")
    if max_candidates<1:
        raise ValueError("max_candidates must be positive")
    if bandwidth_mhz not in (1,2,4,8):
        raise ValueError("this receiver supports 1, 2, 4, or 8 MHz")
    if sample_rate < bandwidth_mhz*1e6 or abs(offset_hz)+bandwidth_mhz*0.5e6 > sample_rate*0.5:
        raise ValueError("channel exceeds sample-rate Nyquist span")
    values=np.asarray(samples)
    if values.ndim==2 and values.shape[1]==2 and values.dtype==np.uint8:
        values=values.view(np.int8)
    if not ((values.ndim==2 and values.shape[1]==2 and values.dtype==np.int8) or
            (values.ndim==1 and np.iscomplexobj(values))):
        raise ValueError("samples must be complex IQ or Nx2 signed I/Q")
    if len(values) < sample_rate*0.001:
        raise ValueError("window must contain at least 1 ms of IQ")
    if search_duration is not None and not .001<=search_duration<=len(values)/sample_rate:
        raise ValueError("search_duration must fit inside the IQ window")
    if candidate_hint is not None and (not np.isfinite(candidate_hint) or
                                       not 0 <= candidate_hint < len(values)):
        raise ValueError("candidate_hint must be a sample index inside the IQ window")
    if bandwidth_mhz==1:
        converted=_complex_iq(values)
        return _decode_1mhz_window(converted-np.mean(converted),sample_rate,
                                   offset_hz,max_candidates,search_duration)
    if bandwidth_mhz==2:
        sub_offset=offset_hz
    else:
        sub_offset=offset_hz+1e6
    search_input=values if search_duration is None else values[:min(len(values),round((search_duration+.001)*sample_rate))]
    search_input=_complex_iq(search_input)
    dc=np.mean(search_input)
    search_input=search_input-dc
    sub=_resample(search_input,sample_rate,4e6,sub_offset)
    search_end=len(sub) if search_duration is None else min(len(sub),round(search_duration*4e6))
    peaks,score=_candidates(sub[:search_end])
    if candidate_hint is not None:
        # The raw STF detector already gives a local PPDU location. A strong
        # periodic interferer can have a higher normalized score than the
        # actual preamble, exhausting a small candidate budget first. Keep
        # the score as a tie breaker and require SIG CRC plus MPDU FCS.
        hint=round(candidate_hint*4e6/sample_rate)
        peaks.sort(key=lambda p:(abs(p-hint),-score[p]))
    full=None
    sub_payload=None
    payload_input_len=0
    recovered=[]
    examined=0
    attempted=set()
    for peak in peaks:
        if examined>=max_candidates:
            break
        examined+=1
        # The normalized STF plateau has no unique maximum: measured peaks
        # can coincide with the real start or be tens of samples away. The
        # STF timing estimator has periodic aliases, and even an aliased
        # LTF/SIG can pass SIG CRC while its data FFTs fail FCS. Try a small
        # fixed set of preamble origins and accept only FCS-checked MPDUs.
        # Wide-channel timing uses a separate full-band search below.
        for delta in ((16,32,0,48) if bandwidth_mhz==2 else (32,)):
            start=max(0,int(peak)-delta)
            try:
                refined,sto,cfo,h,bits,long_format=_preamble_2(sub,start)
                sig=_parse_sig(bits,bandwidth_mhz,long_format)
                if long_format and bandwidth_mhz != 2:
                    raise PhyReject("wide-channel S1G_LONG not yet supported")
                # Several STF plateau samples converge on the same LTF/SIG.
                # A false but CRC-valid SIG can otherwise repeat a long FEC
                # decode for every start in that plateau.
                attempt=(refined,bytes(np.packbits(bits)))
                if attempt in attempted:
                    continue
                attempted.add(attempt)
                cfo_hz=cfo*4e6/(2*np.pi)
                needed=_payload_input_end(refined,sig,bandwidth_mhz,sample_rate,len(values))
                if bandwidth_mhz==2:
                    if sub_payload is None or needed>payload_input_len:
                        sub_payload=_resample(_complex_iq(values[:needed])-dc,
                                              sample_rate,4e6,sub_offset)
                        payload_input_len=needed
                    frames=[]
                    for phase_mode, timing_shift in (("fit",0), ("common",0),
                                                     ("fit",2), ("fit",3)):
                        try:
                            frames=_payload_2(sub_payload,refined+timing_shift,
                                              sto,cfo,h,sig,phase_mode)
                        except PhyReject:
                            continue
                        if frames:
                            break
                else:
                    if full is None or needed>payload_input_len:
                        full=_resample(_complex_iq(values[:needed])-dc,
                                       sample_rate,bandwidth_mhz*1e6,offset_hz)
                        payload_input_len=needed
                    frames=[]
                    timing_shifts=list(range(bandwidth_mhz,bandwidth_mhz+49,4))
                    if bandwidth_mhz==8:
                        # On some 8 MHz SDR captures the duplicated LTF can
                        # give a CRC-valid SIG while the full-band FFT origin
                        # is one symbol period farther into the plateau.
                        # Retry only after the cheap normal search fails;
                        # every output still needs an MPDU FCS.
                        timing_shifts.extend(range(58,107,2))
                    for timing_shift in timing_shifts:
                        full_start=round(refined*bandwidth_mhz/4)+timing_shift
                        for phase_mode in (("fit", "common") if bandwidth_mhz == 4 else ("fit",)):
                            try:
                                frames=_payload_wide(full,full_start,cfo_hz,sig,
                                                     bandwidth_mhz,phase_mode)
                            except PhyReject:
                                continue
                            if frames:
                                break
                        if frames:
                            break
                for frame in frames:
                    original_offset=round(refined*sample_rate/4e6)
                    recovered.append(RecoveredFrame(frame,original_offset,bandwidth_mhz,
                        sig["mcs"],sig["ppdu_format"],sig["short_gi"],float(cfo_hz)))
                if frames:
                    break
            except (PhyReject,ValueError,IndexError,ZeroDivisionError,FloatingPointError):
                continue
    # One STF plateau can yield several candidate maxima. Do not publish a
    # duplicate MPDU from the same transmission window.
    unique=[]
    for frame in sorted(recovered,key=lambda f:f.sample_offset):
        if not any(abs(frame.sample_offset-prior.sample_offset)<round(sample_rate*0.0002)
                   and frame.mpdu==prior.mpdu for prior in unique):
            unique.append(frame)
    return unique
