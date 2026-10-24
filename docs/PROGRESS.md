# Progress

No phase in progress. Next: owner's manual tests of Rheem EcoNet and the
Samsung TV, then the next integration.

## Done
- UI phase (docs/PLAN-UI.md).
- Rheem EcoNet (docs/PLAN-RHEEM.md): E1-E5 by the
  reviewer, E6 by the agent.
- Two-factor login and Samsung TVs (reviewer, 2026-10-22; 204 tests and
  every check pass):
  - Owner decision: two-factor login is each person's choice (My account,
    turning it off needs the password and a current code); an owner can
    require it for everyone in a home (Settings > Users). This replaces the
    earlier rule that every account must use two-factor.
  - Samsung TVs on the home network: 2016 and newer through samsungtvws,
    2010-2013 models through the legacy protocol (a checkbox when adding a
    TV). 2014-2015 (H and J series, encrypted protocol) are not supported.
    Exact volume is simulated-only; real TVs use volume up and down.

- Lights and plugs, and Frigate (reviewer, 2026-10-23; 223 tests and every
  check pass):
  - Lights: brightness, white temperature (2000-6500 K) and RGB colour;
    plugs: on/off. Simulated until the GE Cync integration exists.
  - Frigate 0.14+: the owner saves its address (this machine or the home
    network) and, for the login port, a username and password (encrypted).
    Everyone in the home sees recent events with thumbnails and plays
    clips on the Cameras page; media passes through this app.

## Open items

## Blocked
