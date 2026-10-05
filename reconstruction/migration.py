"""
Stolt (F-K) migration of zero-offset GPR data on a regular 3D grid.

WHY STOLT FOR V1. It is exact for a constant-velocity medium sampled on a
regular grid, deterministic, and fast (three FFTs and one interpolation). A
known-geometry calibration gives exactly one constant velocity, and a BAM grid
is exactly regular. Its assumptions are stated on every product:

  * zero-offset (the antenna's transmitter and receiver are treated as
    coincident -- the common approximation for a ground-coupled bistatic
    antenna whose offset is small against the depths imaged);
  * constant velocity v throughout the imaged volume;
  * the exploding-reflector model (one-way velocity v/2);
  * regular sampling, spatially unaliased: trace spacing <= wavelength / 4 is
    checked and reported, never assumed.

THE MAPPING. With D(kx, ky, f) the FFT of the time-zero-corrected data
d(x, y, t) and M(kx, ky, kz) the image spectrum,

    f(kz) = (v / 2) * sqrt(kx^2 + ky^2 + kz^2)
    M(kx, ky, kz) = D(kx, ky, f(kz)) * kz / sqrt(kx^2 + ky^2 + kz^2)

(cycles per metre and cycles per ns; the last factor is the standard Jacobian
/ obliquity term). The image is sampled at dz = v * dt / 2, so a flat
reflector at time t maps to depth v * t / 2 exactly and the kz Nyquist equals
the time Nyquist. Evanescent components (f beyond the data Nyquist) are
zeroed. Zero padding in x, y and t limits wrap-around; it is stated.
"""
from __future__ import annotations

import numpy as np


def spatial_aliasing_check(dx_m: float, dy_m: float, v_m_per_ns: float, f_max_ghz: float) -> dict:
    """Quarter-wavelength rule at the highest frequency carried."""
    lam = v_m_per_ns / f_max_ghz          # wavelength in the medium, m
    limit = lam / 4.0
    return {"wavelength_m_at_f_max": lam, "quarter_wavelength_m": limit,
            "trace_spacing_m": dx_m, "line_spacing_m": dy_m,
            "unaliased": bool(dx_m <= limit and dy_m <= limit)}


def stolt_migrate(data: np.ndarray, dx_m: float, dy_m: float, dt_ns: float, v_m_per_ns: float,
                  pad_xy: int = 32, pad_t_fraction: float = 0.25) -> np.ndarray:
    """
    Migrate `data` (nx, ny, nt), time already measured from time zero, into an
    image (nx, ny, nt) sampled at dz = v * dt / 2. float32 in, float32 out.
    """
    nx, ny, nt = data.shape
    nxp, nyp = nx + 2 * pad_xy, ny + 2 * pad_xy
    ntp = int(np.ceil(nt * (1 + pad_t_fraction) / 2) * 2)
    buf = np.zeros((nxp, nyp, ntp), np.float32)
    buf[pad_xy:pad_xy + nx, pad_xy:pad_xy + ny, :nt] = data
    spec = np.fft.rfft(buf, axis=2).astype(np.complex64)          # (nxp, nyp, nf)
    del buf
    spec = np.fft.fft2(spec, axes=(0, 1)).astype(np.complex64)
    f = np.fft.rfftfreq(ntp, d=dt_ns)                              # cycles / ns
    df = f[1] - f[0]
    nf = f.size
    dz = v_m_per_ns * dt_ns / 2.0
    kz = np.fft.rfftfreq(ntp, d=dz)                                # cycles / m
    kx = np.fft.fftfreq(nxp, d=dx_m)
    ky = np.fft.fftfreq(nyp, d=dy_m)
    out = np.zeros_like(spec)
    half_v = v_m_per_ns / 2.0
    for ix in range(nxp):
        k2 = kx[ix] ** 2 + ky[:, None] ** 2 + kz[None, :] ** 2      # (nyp, nkz)
        kk = np.sqrt(k2)
        fq = half_v * kk
        pos = fq / df
        i0 = np.floor(pos).astype(np.int64)
        w = (pos - i0).astype(np.float32)
        ok = i0 + 1 < nf
        i0c = np.clip(i0, 0, nf - 2)
        row = spec[ix]                                              # (nyp, nf)
        g0 = np.take_along_axis(row, i0c, axis=1)
        g1 = np.take_along_axis(row, i0c + 1, axis=1)
        val = (1 - w) * g0 + w * g1
        jac = np.where(kk > 0, kz[None, :] / np.maximum(kk, 1e-12), 1.0).astype(np.float32)
        out[ix] = np.where(ok, val * jac, 0)
    del spec
    img = np.fft.ifft2(out, axes=(0, 1))
    del out
    img = np.fft.irfft(img, n=ntp, axis=2).astype(np.float32)
    return np.ascontiguousarray(img[pad_xy:pad_xy + nx, pad_xy:pad_xy + ny, :nt])
