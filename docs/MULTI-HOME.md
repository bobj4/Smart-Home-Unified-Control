# More than one home

## Homes on one server

Admin › Home:

- **This home:** its name, an optional address, and its icon. The icon is a
  built-in one or a small picture of your own (PNG, JPEG or WebP, shrunk to
  128 pixels). It shows at the top right; with more than one home, click it
  to switch homes.
- **Your homes:** every home you belong to, in your own order (↑ ↓). The top
  one opens on your first login; after that, the last one you viewed.
- **Add a Home** (at the bottom): you become its admin. It starts with the
  recommended safety limits, and its own devices, rooms, integrations,
  people and guests.

Thermostats, cameras and devices belong to one home. Roles are per home, so
someone can be an admin of one home and a guest of another. A guest's
permissions (Users › the guest › Guest access) apply to that home only.

## A home at another site

For a second location with a server of its own (the same app, installed
there the usual way), the two servers can be linked. People, logins, roles
and guests stay on the **main server**. The devices, their integrations and
their state stay at the **site**, and so does the site's own login for its
admins.

The site's server connects out to the main server and keeps the connection
open. It needs no open port or port forwarding at the site, only internet
access to the main server's HTTPS address.

1. On the main server: open the home (or Add a Home for it), then Admin ›
   Home › Another site › **Its devices are at another site**. You get a
   pairing code. It works once, within half an hour.
2. On the site's server: Admin › Home › Another site › **this server is at
   another site**. Enter the main server's address (`https://…`) and the
   code.

From then on, using that home on the main server uses the site's devices.
Each request goes to the site with the person's role (admin, operator or
member), and the site applies its own rules as well. On the site, it runs as
a user named "Main server (role)". Guests are handled on the main server:
it shows them only what their guest permissions allow, and sends on only
the commands they may give.

If the site's server is offline, that home's pages say "This home's server
at the other site is not connected right now". The main server's other
homes keep working. **Unlink** (on either side) ends the link. Unlinking on
the main server turns the home back into a home on the main server, with
no devices.

**Proxy:** the site connects to `wss://<main>/api/v1/federation/connect`.
The example Apache and nginx configs (`deploy/proxy/`) pass it through
already; Caddy needs nothing extra. With Apache on Debian or Ubuntu, run
`a2enmod proxy_wstunnel` once.

**Without a second server at the site:** devices that are only reached
through their cloud (Cync, SmartThings, Rheem EcoNet) work from the main
server directly; add the home there and connect those integrations. Devices
reached on the site's own network (Hue, Kasa, TVs, ratgdo, Frigate) need
something at the site. That can be a small server running this app (a
Raspberry Pi is enough), linked as above, or a VPN between the sites.
