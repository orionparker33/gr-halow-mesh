# SPDX-License-Identifier: GPL-3.0-or-later
"""Development diagnostic for S1G-like OFDM symbols in signed 8-bit IQ.

This detects a 32 us OFDM useful-symbol repetition, not an 802.11ah packet.
Only an independently validated S1G SIG/PSDU/FCS chain can claim a decode.
"""

import numpy as np
from scipy.signal import firwin, lfilter


def _moving_sum(x, count):
    prefix = np.empty(len(x) + 1, dtype=x.dtype)
    prefix[0] = 0
    np.cumsum(x, out=prefix[1:])
    return prefix[count:] - prefix[:-count]


def inspect_iq(samples, sample_rate, bandwidth_mhz=8, offset_hz=0):
    """Return best long-GI CP correlation and FFT spread in a bounded window.

    ``samples`` is Nx2 signed I/Q. A narrow tone may correlate with any lag,
    so effective FFT bins are reported alongside the correlation score.
    """
    samples = np.asarray(samples)
    if samples.ndim != 2 or samples.shape[1] != 2:
        raise ValueError("samples must be Nx2 I/Q")
    if not 1e6 <= sample_rate <= 25e6:
        raise ValueError("sample rate outside supported diagnostic range")
    if bandwidth_mhz not in (1, 2, 4, 8, 16):
        raise ValueError("bandwidth must be 1, 2, 4, 8, or 16 MHz")
    if abs(offset_hz) + bandwidth_mhz * 0.5e6 >= sample_rate * 0.5:
        raise ValueError("selected channel exceeds recorded Nyquist span")
    lag = round(sample_rate * 32e-6)
    guard = round(sample_rate * 8e-6)
    if len(samples) < lag + guard + lag:
        raise ValueError("IQ window too short")
    values = samples.astype(np.float32)
    dc = values.mean(axis=0)
    centered = values - dc
    raw_signal = centered[:, 0] + 1j * centered[:, 1]
    n = np.arange(len(raw_signal))
    shifted = raw_signal * np.exp(-2j * np.pi * offset_hz * n / sample_rate)
    taps = firwin(129, bandwidth_mhz * 0.47e6, fs=sample_rate)
    signal = lfilter(taps, 1, shifted)
    products = signal[:-lag] * np.conj(signal[lag:])
    pair_power = (np.abs(signal[:-lag]) ** 2 + np.abs(signal[lag:]) ** 2) * 0.5
    corr = _moving_sum(products, guard)
    power = _moving_sum(pair_power, guard)
    valid = len(signal) - 2 * lag - guard + 1
    scores = np.abs(corr[:valid]) / np.maximum(power[:valid], 1e-9)
    valid_power = power[:valid]
    peak = int(np.argmax(scores * np.sqrt(valid_power)))
    symbol = signal[peak + guard:peak + guard + lag]
    bins = np.abs(np.fft.fft(symbol)) ** 2
    total = float(bins.sum())
    spread = float(total ** 2 / np.sum(bins ** 2)) if total else 0.0
    # The FIR has a 64-sample group delay. Measure how much of the original
    # symbol energy was inside the selected channel before filtering.
    original_at = max(0, peak + guard - 64)
    original = raw_signal[original_at:original_at + lag]
    raw_bins = np.abs(np.fft.fft(original)) ** 2
    freqs = np.fft.fftfreq(lag, 1 / sample_rate)
    selected = np.abs(freqs - offset_hz) < bandwidth_mhz * 0.5e6
    selected_fraction = float(raw_bins[selected].sum() / raw_bins.sum()) if raw_bins.sum() else 0.0
    return {
        "sample_offset": peak,
        "cp_score": round(float(scores[peak]), 5),
        "effective_fft_bins": round(spread, 2),
        "selected_band_energy_fraction": round(selected_fraction, 4),
        "bandwidth_mhz": bandwidth_mhz,
        "offset_hz": offset_hz,
        "dc_iq": [round(float(x), 3) for x in dc],
        "clipped_fraction": round(float(np.mean(np.any(np.abs(values) >= 126, axis=1))), 6),
        "useful_symbol_samples": lag,
        "guard_samples": guard,
    }
