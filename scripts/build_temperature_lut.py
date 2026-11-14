"""Builds temperature_data/surface_temperature_lut.npz, the lookup table temperature.py reads.

A 1-D thermal model of the Martian ground (the same idea as the KRC model used to
derive the TES and THEMIS thermal inertia maps, much simplified): for every
combination of latitude, thermal inertia and albedo it steps the heat equation
through three Mars years and records the surface temperature of the last year
for every hour of the day in 24 seasons.

    surface:   eps*sigma*T^4 = absorbed sunlight + sky infrared + heat conducted from below
    below:     dT/dt = (pi / P) * d2T/dz'2          (z' = depth in diurnal skin depths)
    CO2 frost: the surface cannot drop below the CO2 frost point; the energy deficit
               builds a frost layer that has to sublimate before the ground warms again

Sunlight uses Mars' real orbit (eccentricity, obliquity). The atmosphere is the
simple scheme of Schorghofer's planetary-code "flux_mars": a few percent of the
beam is absorbed or scattered, and the sky radiates a few percent of the noon flux.
Dust storms are not modelled: during one, days are colder and nights warmer than shown.

Run:  .venv/bin/python scripts/build_temperature_lut.py      (about a minute)
"""
from pathlib import Path

import numpy as np

OUT = Path(__file__).parent.parent / "temperature_data/surface_temperature_lut.npz"

# --- Table axes ---
LATS = np.arange(-90, 91, 5.0)
INERTIAS = np.array([20, 40, 70, 110, 160, 220, 300, 420, 600, 900, 1400, 2200.0])  # J m-2 K-1 s-1/2
ALBEDOS = np.array([0.08, 0.14, 0.20, 0.26, 0.32])
N_LS, N_HOURS = 24, 24                      # seasons every 15 deg of Ls, hours of local true solar time

# --- Mars ---
SOL = 88775.244                             # s
YEAR_SOLS = 668.6
ECC, LS_PERIHELION, OBLIQUITY = 0.0934, 251.0, 25.19
SEMI_MAJOR_AU, SOLAR_CONSTANT = 1.52368, 1361.0
SIGMA, EMISSIVITY = 5.670374e-8, 0.98
FRAC_IR, FRAC_DUST = 0.04, 0.02             # sky infrared and dust scattering, as fractions of the solar flux
T_FROST, L_CO2 = 148.0, 5.9e5               # CO2 frost point at ~6 mbar (K), latent heat (J/kg)
FROST_ALBEDO, FROST_EMISSIVITY = 0.60, 0.80

STEPS_PER_SOL = 96
YEARS = 3


def solar_longitude(sol):
    """Ls (deg) and Sun distance (AU) for a time in sols since perihelion."""
    m = 2 * np.pi * sol / YEAR_SOLS
    e = m
    for _ in range(8):
        e = e - (e - ECC * np.sin(e) - m) / (1 - ECC * np.cos(e))
    nu = 2 * np.arctan2(np.sqrt(1 + ECC) * np.sin(e / 2), np.sqrt(1 - ECC) * np.cos(e / 2))
    return (np.degrees(nu) + LS_PERIHELION) % 360, SEMI_MAJOR_AU * (1 - ECC * np.cos(e))


def main():
    lat, inertia, albedo = [a.ravel() for a in np.meshgrid(LATS, INERTIAS, ALBEDOS, indexing="ij")]
    lat = np.radians(lat)
    n = lat.size

    # Layers, in diurnal skin depths, thickening downward to ~4 seasonal skin depths.
    thick = 0.15 * 1.22 ** np.arange(26)
    centre = np.cumsum(thick) - thick / 2
    dt = SOL / STEPS_PER_SOL
    r = np.pi / SOL * dt
    up = np.empty_like(thick)                # conductance to the node above / below, per layer thickness
    up[0] = r / (thick[0] * thick[0] / 2)
    up[1:] = r / (thick[1:] * (centre[1:] - centre[:-1]))
    down = np.zeros_like(thick)
    down[:-1] = r / (thick[:-1] * (centre[1:] - centre[:-1]))
    # Backward-Euler elimination from the bottom: T[i] = a[i] * T[i-1] + b[i]
    nl = thick.size
    a = np.empty(nl)
    denom = np.empty(nl)
    denom[-1] = 1 + up[-1]
    a[-1] = up[-1] / denom[-1]
    for i in range(nl - 2, -1, -1):
        denom[i] = 1 + up[i] + down[i] * (1 - a[i + 1])
        a[i] = up[i] / denom[i]
    gamma = inertia * np.sqrt(np.pi / SOL) / (thick[0] / 2)   # W m-2 K-1 between surface and first layer

    temp = np.full((nl, n), 200.0)
    surf = np.full(n, 200.0)
    frost = np.zeros(n)                      # kg m-2 of CO2 frost
    b = np.empty((nl, n))

    target_ls = (np.arange(N_LS) + 0.5) * 360 / N_LS
    total_sols = int(YEARS * YEAR_SOLS)
    first_recorded = int((YEARS - 1) * YEAR_SOLS)
    ls_of_sol = solar_longitude(np.arange(total_sols) + 0.5)[0]
    record_sol = {first_recorded + int(np.argmin(np.abs((ls_of_sol[first_recorded:] - t + 180) % 360 - 180))): k
                  for k, t in enumerate(target_ls)}
    out = np.empty((N_LS, N_HOURS, n), dtype=np.float32)

    for sol in range(total_sols):
        ls, dist = solar_longitude(sol + 0.5)
        flux = SOLAR_CONSTANT / dist**2
        dec = np.arcsin(np.sin(np.radians(OBLIQUITY)) * np.sin(np.radians(ls)))
        noon = np.clip(np.sin(lat) * np.sin(dec) + np.cos(lat) * np.cos(dec), 0, 1)
        sky_ir = FRAC_IR * flux * noon
        for step in range(STEPS_PER_SOL):
            hour = (step + 1) * 24 / STEPS_PER_SOL
            cosi = np.sin(lat) * np.sin(dec) + np.cos(lat) * np.cos(dec) * np.cos(np.radians(15 * (hour - 12)))
            sun = np.where(cosi > 0,
                           flux * cosi * (1 - FRAC_IR - FRAC_DUST) ** (1 / np.maximum(cosi, 0.04)) + 0.5 * FRAC_DUST * flux,
                           0.0)
            frosted = frost > 0
            alb = np.where(frosted, FROST_ALBEDO, albedo)
            eps = np.where(frosted, FROST_EMISSIVITY, EMISSIVITY)
            absorbed = (1 - alb) * sun + eps * sky_ir

            # Upward sweep: first-layer temperature as a linear function of the new surface temperature.
            b[-1] = temp[-1] / denom[-1]
            for i in range(nl - 2, -1, -1):
                b[i] = (temp[i] + down[i] * b[i + 1]) / denom[i]
            # Newton on the surface balance  eps*sigma*T^4 + gamma*(T - T0) = absorbed,  T0 = a0*T + b0
            t = surf.copy()
            for _ in range(4):
                f = eps * SIGMA * t**4 + gamma * ((1 - a[0]) * t - b[0]) - absorbed
                t = np.maximum(t - f / (4 * eps * SIGMA * t**3 + gamma * (1 - a[0])), 50.0)
            # CO2 frost: hold the frost point while frost exists or would form.
            deficit = eps * SIGMA * T_FROST**4 + gamma * ((1 - a[0]) * T_FROST - b[0]) - absorbed   # W m-2 lost at T_FROST
            cold = frosted | (t < T_FROST)
            frost = np.where(cold, np.maximum(frost + deficit * dt / L_CO2, 0.0), 0.0)
            surf = np.where(cold & ((frost > 0) | (t < T_FROST)), T_FROST, t)
            # Downward sweep.
            temp[0] = a[0] * surf + b[0]
            for i in range(1, nl):
                temp[i] = a[i] * temp[i - 1] + b[i]

            if sol in record_sol and (step + 1) % (STEPS_PER_SOL // N_HOURS) == 0:
                out[record_sol[sol], int(round(hour)) % 24] = surf

    out = out.reshape(N_LS, N_HOURS, LATS.size, INERTIAS.size, ALBEDOS.size)
    OUT.parent.mkdir(exist_ok=True)
    np.savez_compressed(OUT, kelvin_x10=np.round(out * 10).astype(np.int16), ls=target_ls,
                        hour=np.arange(N_HOURS, dtype=np.float32), lat=LATS, inertia=INERTIAS, albedo=ALBEDOS)
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB), {out.min():.0f}..{out.max():.0f} K")


if __name__ == "__main__":
    main()
