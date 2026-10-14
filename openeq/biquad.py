"""
Biquad filter coefficient calculator.

Implements the Audio EQ Cookbook (Robert Bristow-Johnson) formulas
for all filter types supported by Equalizer APO / Peace.
"""

import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class FilterType(Enum):
    """Supported biquad filter types matching Equalizer APO."""
    PK = "PK"           # peaking eq
    PEQ = "PEQ"         # parametric eq (alias for pk)
    MODAL = "Modal"     # modal (alias for pk)
    LP = "LP"           # low-pass
    LPQ = "LPQ"         # low-pass with q
    HP = "HP"           # high-pass
    HPQ = "HPQ"         # high-pass with q
    BP = "BP"           # band-pass
    LS = "LS"           # low-shelf
    HS = "HS"           # high-shelf
    LS6 = "LS6dB"       # low-shelf 6db/oct
    LS12 = "LS12dB"     # low-shelf 12db/oct
    HS6 = "HS6dB"       # high-shelf 6db/oct
    HS12 = "HS12dB"     # high-shelf 12db/oct
    NO = "NO"           # notch
    AP = "AP"           # all-pass


@dataclass
class BiquadCoeffs:
    """Biquad filter coefficients (normalized by a0)."""
    b0: float
    b1: float
    b2: float
    a1: float
    a2: float

    def to_dict(self):
        return {
            "b0": self.b0, "b1": self.b1, "b2": self.b2,
            "a1": self.a1, "a2": self.a2,
        }


@dataclass
class FilterParams:
    """Parameters for a single biquad filter band."""
    filter_type: FilterType
    frequency: float        # center/corner frequency in hz
    gain: float = 0.0       # gain in db (for peaking/shelf)
    q: Optional[float] = None
    bandwidth: Optional[float] = None  # in octaves
    enabled: bool = True

    def effective_q(self) -> float:
        """Return Q, converting from bandwidth if needed."""
        if self.q is not None:
            return self.q
        if self.bandwidth is not None:
            # convert bandwidth in octaves to q
            bw = self.bandwidth
            return math.sqrt(2**bw) / (2**bw - 1)
        # default q values per filter type
        defaults = {
            FilterType.LP: 0.7071,
            FilterType.HP: 0.7071,
            FilterType.BP: 1.0,
            FilterType.LS: 0.7071,
            FilterType.HS: 0.7071,
            FilterType.NO: 30.0,
            FilterType.AP: 0.7071,
        }
        return defaults.get(self.filter_type, 1.0)


def compute_coefficients(params: FilterParams, sample_rate: int = 48000) -> BiquadCoeffs:
    """
    Compute biquad coefficients using the Audio EQ Cookbook formulas.

    Reference: Robert Bristow-Johnson's Audio EQ Cookbook
    """
    fc = params.frequency
    gain_db = params.gain
    q = params.effective_q()
    fs = sample_rate

    # clamp frequency to valid range
    fc = max(1.0, min(fc, fs / 2.0 - 1.0))

    w0 = 2.0 * math.pi * fc / fs
    cos_w0 = math.cos(w0)
    sin_w0 = math.sin(w0)
    alpha = sin_w0 / (2.0 * q)
    A = 10.0 ** (gain_db / 40.0)  # sqrt of linear gain

    ft = params.filter_type

    if ft in (FilterType.PK, FilterType.PEQ, FilterType.MODAL):
        # peaking eq
        b0 = 1.0 + alpha * A
        b1 = -2.0 * cos_w0
        b2 = 1.0 - alpha * A
        a0 = 1.0 + alpha / A
        a1 = -2.0 * cos_w0
        a2 = 1.0 - alpha / A

    elif ft in (FilterType.LP, FilterType.LPQ):
        # low-pass
        b0 = (1.0 - cos_w0) / 2.0
        b1 = 1.0 - cos_w0
        b2 = (1.0 - cos_w0) / 2.0
        a0 = 1.0 + alpha
        a1 = -2.0 * cos_w0
        a2 = 1.0 - alpha

    elif ft in (FilterType.HP, FilterType.HPQ):
        # high-pass
        b0 = (1.0 + cos_w0) / 2.0
        b1 = -(1.0 + cos_w0)
        b2 = (1.0 + cos_w0) / 2.0
        a0 = 1.0 + alpha
        a1 = -2.0 * cos_w0
        a2 = 1.0 - alpha

    elif ft == FilterType.BP:
        # band-pass (constant skirt gain, peak gain = q)
        b0 = alpha
        b1 = 0.0
        b2 = -alpha
        a0 = 1.0 + alpha
        a1 = -2.0 * cos_w0
        a2 = 1.0 - alpha

    elif ft == FilterType.LS:
        # low-shelf
        sq = 2.0 * math.sqrt(A) * alpha
        b0 = A * ((A + 1.0) - (A - 1.0) * cos_w0 + sq)
        b1 = 2.0 * A * ((A - 1.0) - (A + 1.0) * cos_w0)
        b2 = A * ((A + 1.0) - (A - 1.0) * cos_w0 - sq)
        a0 = (A + 1.0) + (A - 1.0) * cos_w0 + sq
        a1 = -2.0 * ((A - 1.0) + (A + 1.0) * cos_w0)
        a2 = (A + 1.0) + (A - 1.0) * cos_w0 - sq

    elif ft == FilterType.HS:
        # high-shelf
        sq = 2.0 * math.sqrt(A) * alpha
        b0 = A * ((A + 1.0) + (A - 1.0) * cos_w0 + sq)
        b1 = -2.0 * A * ((A - 1.0) + (A + 1.0) * cos_w0)
        b2 = A * ((A + 1.0) + (A - 1.0) * cos_w0 - sq)
        a0 = (A + 1.0) - (A - 1.0) * cos_w0 + sq
        a1 = 2.0 * ((A - 1.0) - (A + 1.0) * cos_w0)
        a2 = (A + 1.0) - (A - 1.0) * cos_w0 - sq

    elif ft == FilterType.LS6:
        # low-shelf 6db/oct (first-order approximation via biquad)
        A_lin = 10.0 ** (gain_db / 20.0)
        w0_c = 2.0 * math.pi * fc / fs
        cos_c = math.cos(w0_c)
        sin_c = math.sin(w0_c)
        a_lp = sin_c / (2.0 * 0.7071)
        b0 = A_lin * ((A_lin + 1.0) - (A_lin - 1.0) * cos_c + 2.0 * math.sqrt(A_lin) * a_lp)
        b1 = 2.0 * A_lin * ((A_lin - 1.0) - (A_lin + 1.0) * cos_c)
        b2 = A_lin * ((A_lin + 1.0) - (A_lin - 1.0) * cos_c - 2.0 * math.sqrt(A_lin) * a_lp)
        a0 = (A_lin + 1.0) + (A_lin - 1.0) * cos_c + 2.0 * math.sqrt(A_lin) * a_lp
        a1 = -2.0 * ((A_lin - 1.0) + (A_lin + 1.0) * cos_c)
        a2 = (A_lin + 1.0) + (A_lin - 1.0) * cos_c - 2.0 * math.sqrt(A_lin) * a_lp

    elif ft == FilterType.LS12:
        # low-shelf 12db/oct (steeper shelf)
        A_lin = 10.0 ** (gain_db / 20.0)
        q12 = 0.5
        alpha12 = sin_w0 / (2.0 * q12)
        sq12 = 2.0 * math.sqrt(A_lin) * alpha12
        b0 = A_lin * ((A_lin + 1.0) - (A_lin - 1.0) * cos_w0 + sq12)
        b1 = 2.0 * A_lin * ((A_lin - 1.0) - (A_lin + 1.0) * cos_w0)
        b2 = A_lin * ((A_lin + 1.0) - (A_lin - 1.0) * cos_w0 - sq12)
        a0 = (A_lin + 1.0) + (A_lin - 1.0) * cos_w0 + sq12
        a1 = -2.0 * ((A_lin - 1.0) + (A_lin + 1.0) * cos_w0)
        a2 = (A_lin + 1.0) + (A_lin - 1.0) * cos_w0 - sq12

    elif ft == FilterType.HS6:
        # high-shelf 6db/oct
        A_lin = 10.0 ** (gain_db / 20.0)
        a_hp = sin_w0 / (2.0 * 0.7071)
        sq_h = 2.0 * math.sqrt(A_lin) * a_hp
        b0 = A_lin * ((A_lin + 1.0) + (A_lin - 1.0) * cos_w0 + sq_h)
        b1 = -2.0 * A_lin * ((A_lin - 1.0) + (A_lin + 1.0) * cos_w0)
        b2 = A_lin * ((A_lin + 1.0) + (A_lin - 1.0) * cos_w0 - sq_h)
        a0 = (A_lin + 1.0) - (A_lin - 1.0) * cos_w0 + sq_h
        a1 = 2.0 * ((A_lin - 1.0) - (A_lin + 1.0) * cos_w0)
        a2 = (A_lin + 1.0) - (A_lin - 1.0) * cos_w0 - sq_h

    elif ft == FilterType.HS12:
        # high-shelf 12db/oct
        A_lin = 10.0 ** (gain_db / 20.0)
        q12 = 0.5
        alpha12 = sin_w0 / (2.0 * q12)
        sq12 = 2.0 * math.sqrt(A_lin) * alpha12
        b0 = A_lin * ((A_lin + 1.0) + (A_lin - 1.0) * cos_w0 + sq12)
        b1 = -2.0 * A_lin * ((A_lin - 1.0) + (A_lin + 1.0) * cos_w0)
        b2 = A_lin * ((A_lin + 1.0) + (A_lin - 1.0) * cos_w0 - sq12)
        a0 = (A_lin + 1.0) - (A_lin - 1.0) * cos_w0 + sq12
        a1 = 2.0 * ((A_lin - 1.0) - (A_lin + 1.0) * cos_w0)
        a2 = (A_lin + 1.0) - (A_lin - 1.0) * cos_w0 - sq12

    elif ft == FilterType.NO:
        # notch
        b0 = 1.0
        b1 = -2.0 * cos_w0
        b2 = 1.0
        a0 = 1.0 + alpha
        a1 = -2.0 * cos_w0
        a2 = 1.0 - alpha

    elif ft == FilterType.AP:
        # all-pass
        b0 = 1.0 - alpha
        b1 = -2.0 * cos_w0
        b2 = 1.0 + alpha
        a0 = 1.0 + alpha
        a1 = -2.0 * cos_w0
        a2 = 1.0 - alpha

    else:
        raise ValueError(f"Unsupported filter type: {ft}")

    # normalize by a0
    return BiquadCoeffs(
        b0=b0 / a0,
        b1=b1 / a0,
        b2=b2 / a0,
        a1=a1 / a0,
        a2=a2 / a0,
    )


def compute_frequency_response(
    filters: list[FilterParams],
    preamp_db: float = 0.0,
    sample_rate: int = 48000,
    num_points: int = 512,
) -> tuple[list[float], list[float]]:
    """
    Compute the combined frequency response of a filter chain.

    Returns (frequencies_hz, magnitudes_db).
    """
    import cmath

    freqs = []
    mags = []

    preamp_linear = 10.0 ** (preamp_db / 20.0)

    for i in range(num_points):
        # log-spaced from 20 hz to nyquist
        f = 20.0 * (sample_rate / 2.0 / 20.0) ** (i / (num_points - 1))
        freqs.append(f)

        w = 2.0 * cmath.pi * f / sample_rate
        z = cmath.exp(1j * w)
        z_inv = 1.0 / z
        z_inv2 = z_inv * z_inv

        total_mag = preamp_linear

        for fp in filters:
            if not fp.enabled:
                continue
            c = compute_coefficients(fp, sample_rate)
            # h(z) = (b0 + b1*z^-1 + b2*z^-2) / (1 + a1*z^-1 + a2*z^-2)
            num = c.b0 + c.b1 * z_inv + c.b2 * z_inv2
            den = 1.0 + c.a1 * z_inv + c.a2 * z_inv2
            h = num / den
            total_mag *= abs(h)

        mag_db = 20.0 * math.log10(max(total_mag, 1e-10))
        mags.append(mag_db)

    return freqs, mags


def compute_response_at_frequencies(
    filters: list[FilterParams],
    preamp_db: float = 0.0,
    frequencies: list[float] = None,
    sample_rate: int = 48000,
) -> list[float]:
    """
    Compute the combined frequency response (in dB) at specific frequencies.

    Used by equalizers to calculate exact gains for target frequency bands
    (such as 10-band, 15-band, 31-band, or PulseAudio LADSPA mbeq_1197 bands).
    """
    import cmath

    if frequencies is None:
        frequencies = [50.0, 100.0, 156.0, 220.0, 311.0, 440.0, 622.0, 880.0,
                       1250.0, 1750.0, 2500.0, 3500.0, 5000.0, 10000.0, 20000.0]

    preamp_linear = 10.0 ** (preamp_db / 20.0)
    mags = []

    for f in frequencies:
        w = 2.0 * cmath.pi * f / sample_rate
        z = cmath.exp(1j * w)
        z_inv = 1.0 / z
        z_inv2 = z_inv * z_inv

        total_mag = preamp_linear

        for fp in filters:
            if not fp.enabled:
                continue
            c = compute_coefficients(fp, sample_rate)
            num = c.b0 + c.b1 * z_inv + c.b2 * z_inv2
            den = 1.0 + c.a1 * z_inv + c.a2 * z_inv2
            h = num / den
            total_mag *= abs(h)

        mag_db = 20.0 * math.log10(max(total_mag, 1e-10))
        mags.append(mag_db)

    return mags

