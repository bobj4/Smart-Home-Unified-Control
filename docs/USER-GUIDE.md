# User Guide

## Logging in

Open the app and enter your email (or username, if the home allows it) and
password, then click **Log in**.

- **Two-factor login**: if you have it on (or the home requires it), enter
  the code from your authenticator app, or one of your recovery codes.
- **Remember this device**: tick it to skip the code on this device; it
  then shows, with a name you choose (suggested as your name and the
  device, such as "Vulture's Samsung S26"), in **My Account › Approved
  devices**.
- **Keep me logged in**: stay logged in on this device for as long as an
  admin allows.
- **Forgot your password?**: ask an admin for a reset code, then follow
  the link to set a new password.
- **Have an enrollment code?**: join a home with the code an admin gave you.

## Roles

- **Admin**: everything, including people, home settings and HTTPS.
- **Operator**: devices, rooms, groups, integrations and safety limits.
- **Member**: uses the devices.
- **Guest**: only what an admin ticks for them (lights, light settings, all
  or some cameras, the water heater, chosen thermostats, scenes).

## The top bar

- **Bell**: your alerts, with a red count of the ones you have not seen.
  Dismiss one with its **×** (on a computer) or by swiping it left or
  right (on a phone); **Dismiss All** at the bottom clears your list. Only
  your list: everyone else still sees them. With nothing in it, it says
  "No notifications".
- **Air filter due**: a thermostat's filter reminder stays at the top of the
  bell (it cannot be dismissed) until the filter is changed. Operators and
  admins press **Changed Filter** in it to start the count again (the
  thermostat's own count too).
- **Home**: switch between homes (when you have more than one).

## Devices

Every device, grouped by room. Rooms fold shut, can be arranged (**Edit
layout**, separately for phones and wide screens) and filtered by type or
"on only". The page updates by itself.

- **Lights**: power, and **Light settings** for brightness, white
  temperature and color.
- **Plugs and switches**: power. A Cync wall switch shows as **Switch**; a
  dimmer switch has a brightness slider.
- **Groups**: lights and plugs switched together; the group's **⋯**
  reaches each device in it.
- **Thermostats and water heaters**: on a page of their own. Targets stay
  within the home's safety limits. A Cync thermostat's **Settings** has an
  **Air filter** reminder among its installer settings: the thermostat's
  own, the same one the Cync app shows (after 100 to 1500 run hours, or 1
  to 12 months). Its Info shows the time left.
- **Garage doors** (ratgdo): open, close and stop on the Doors page, with
  the opener light, remote lockout, obstruction warning and, on a ratgdo32
  disco, the parking-assist laser.
- **TVs**: **Remote** for power, volume, channels, the d-pad, media keys,
  apps and the input. Operators and admins have the TV's **⋯** menu:
  - **Name inputs**: say what is on each input (HDMI 2: PlayStation). The
    remote's Input list then shows "PlayStation (HDMI 2)", and choosing it
    switches the TV by remote key on the home network.
  - **Quick apps** (2016+ Samsung TVs): up to six of the TV's apps for the
    remote's buttons.
- **ⓘ** beside a device (Settings › Devices): its IP and MAC address,
  type and brand.
- **⚡ Energy**: power now and use today, from Kasa plugs that measure it
  and water heaters.

## Schedules and Scenes

- **Schedules** run on the server at a time of day, or at sunrise or sunset
  (minutes before or after), on the days you choose.
- **Scenes** switch devices, groups (and Hue scenes) together with one press.
  A color step has color samples to pick from (or any color with its
  picker).
- **Reset** (on a scene that has run): puts back what the scene changed,
  only that (a brightness step: the brightness), and only where it still
  differs. Running the scene again within 12 hours keeps the first
  "before". Anyone who can run the scene can reset it.

Admins choose who may make and change them, the home's time zone and
location (typed in, or **Use the home's address**), and can pause every
schedule (Settings › Admin › Schedules and Scenes). Thermostat and water
heater schedules stay on their own cards.

## Cameras

Frigate cameras and their recent events with thumbnails; click one to play
the clip.

## Settings › My Account

- **Password**, **2 Factor Login** (authenticator app and recovery codes).
- **Appearance**: light, dark or the device's theme, colors, a background
  picture.
- **Approved devices** and **Logged-in devices**.
- **Alerts**: which of the home's alerts you get, by email and as
  notifications on this phone or computer. On an iPhone, add the app to the
  Home Screen first.

## Settings › Admin

Admins only: people (add, edit, roles, enrollment and reset codes), homes
(name, address, icon, Add a Home), login rules and password requirements,
two-factor for everyone, the message of the day, Schedules and Scenes,
the email server and HTTPS.

## Settings › Devices

Rename devices, choose their room and group, create rooms and groups, and
delete devices. The **bell** beside each device sets what it alerts about:
light grey when on, red and struck through when off. A plain bell turns
alerts on and off; a bell with a plus (garage doors, water heaters,
thermostats) opens its alert settings, such as "open longer than" or "too
hot".

## Settings › Integrations

Each brand is turned on here (one that is off takes no commands and adds no
devices):

- **GE Cync**: your Cync account; lights, plugs, switches, thermostats and
  sensors.
- **Philips Hue**: press the bridge's button to pair.
- **TP-Link Kasa**: each device added by its IP address (newer firmware
  also needs your TP-Link login).
- **Rheem EcoNet**: your EcoNet email and password; **Sync** finds the
  water heaters.
- **Samsung, LG and Roku TVs**: **Find TVs on my network** (leave the
  network blank to search the one you or the server are on), then pair.
  Turn on the TV's **Power On with Mobile** (or "IP Remote") so it can be
  turned on over the network.
- **SmartThings** (optional): Samsung TV inputs by name and turning a TV on
  through Samsung's cloud. SmartThings now needs a paid SmartThings API
  plan for a lasting connection; without it, a personal token works for 24
  hours. Named inputs (above) need no SmartThings.
- **ratgdo garage doors**: added by address.
- **Frigate cameras**: the Frigate server's address and login, and which
  detections send a camera alert.
- **Demo Devices**: simulated devices for trying the app.

## Settings › Safety Settings

The range thermostats and water heaters accept, the target new devices
start at, and who may change thermostat installer settings.

## Settings › Activity Log

Admins only. Logins, setting changes and device commands, newest first.

## Not supported

- Samsung 2014-2015 TVs (H and J series, encrypted protocol)
