# User Guide

## Logging in

Go to the login page. Enter your email or username (as set by your owner) and password, then click **Log in**.

- **Two-factor login**: If your owner requires it, enter the code from your authenticator app.
- **Forgot password?**: Click **Forgot your password?** to get a recovery code from your owner, then follow the link to set a new password.
- **Enrollment code?**: If you have one, click **Have an enrollment code?** to join the household.

## Devices

The Devices page shows all lights, plugs, water heaters and TVs, grouped by room.

### Lights window

Each light has a power toggle and sliders for brightness, white temperature and colour. Click the light card to open the full controls.

### Plugs

Each plug has a power toggle. Click to turn it on or off.

### Water heater

The water heater has a dial with up/down buttons to set the temperature. The range is 110-120°F; the default is 120°F.

### TV remote

Each Samsung TV has a power toggle and buttons for volume up/down, mute, input and power. Volume is simulated-only on real TVs.

## Cameras

The Cameras page shows recent Frigate events with thumbnails. Click a thumbnail to play the clip. Media passes through this app.

## Settings > My account

Open Settings, then click **My account**.

- **Password**: Click **Change password** to set a new one.
- **Two-factor login**: Click **Two-factor login** to turn it on or off. Turning it off requires your password and a current code.
- **Appearance**: Choose light or dark mode.
- **Logged-in devices**: See your active sessions.

## Settings > Users

Open Settings, then click **Users**. Owners can add and edit members.

- Click **Add a member** to invite someone with an enrollment code.
- Click a member to edit their role (member, admin, owner) and password.

## Settings > Integrations

Open Settings, then click **Integrations**.

### Rheem

Owner saves the EcoNet email and password. Click **Find water heaters** to discover devices after sync.

### Samsung TV

Admin or owner adds a TV. Choose 2016+ (samsungtvws) or 2010-2013 (legacy) protocol. 2014-2015 TVs (H and J series) are not supported. Volume is simulated-only.

### Frigate

Owner saves the Frigate address, username and password. Click **Check its HTTPS certificate** (untick for Frigate's own self-signed certificate).

## Settings > Admin

Owners only.

- **Home name**: Set the home's display name.
- **Require two-factor login**: Turn on to require it for all members. Members without it can only open **My account** until they set it up.
- **Login rules**: Choose whether to require email or allow email/username.
- **Password requirements**: Set password rules (length, numbers, symbols).
- **HTTPS**: Toggle HTTPS on or off. The server must be restarted after changing HTTPS.

## Settings > Activity log

Owners only. Shows logins, setting changes and device commands, newest first.

## Not built yet

- GE Cync integration (lights and plugs)
- Samsung 2014-2015 TVs (H and J series, encrypted protocol)
- Live state refresh for devices
- Deployment with HTTPS
