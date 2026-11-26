# Google Nest

Nest thermostats, and Nest camera, doorbell and display alerts, through
Google's **Device Access** (the Smart Device Management API). Code:
`backend/app/integrations/nest.py` (Google's API), `backend/app/nest_home.py`
(sign-in, devices, commands, events), `backend/app/routes/nest.py`,
`web/js/nest.js`.

> **Google charges for this.** Device Access needs a one-time,
> non-refundable **US$5** registration, with a personal Google account
> (gmail.com; Google Workspace accounts are not accepted, and the account
> cannot be changed later). There is no free way in: Google offers no other
> API for Nest devices.

## What it does

- **Thermostats**: on the Thermostats page like a Cync one: temperature,
  humidity, heating/cooling/idle, mode (Heat, Cool, Auto = Google's
  HEATCOOL, Off, Eco), heat and cool set points (within the home's safety
  limits), and the fan (On runs Google's longest fan timer, 12 hours).
  Google works in Celsius; the app shows whole degrees F. Set points cannot
  change in Eco (Google refuses them).
- **Cameras, doorbells and displays**: a card with what it last saw, and
  alerts: each one's bell in Settings › Devices picks person (on), motion,
  sound and doorbell press (on). People choose "A camera sees someone" and
  "Someone rings a doorbell" in My Account › Alerts. No live video.
- Read every 2 minutes (every 10 with events, which also carry changes),
  events every 30 seconds. If the sign-in stops working, the bell says so
  ("Google Nest needs signing in again").

## Setting it up (about 15 minutes)

1. **Register** at <https://console.nest.google.com/device-access> and pay
   the US$5.
2. **Google Cloud**: in a project at <https://console.cloud.google.com>:
   - Enable the **Smart Device Management API** (and **Cloud Pub/Sub API**
     for events).
   - **APIs & Services › OAuth consent screen**: External; add yourself as
     a test user, then **Publish app** (In production). Left in Testing, the
     sign-in stops working after 7 days.
   - **Credentials › Create credentials › OAuth client ID**: Web
     application, authorized redirect URI `https://www.google.com`. Keep the
     client ID and secret.
3. **Device Access project**: in the Device Access console, create a
   project with that OAuth client ID. Copy its **Project ID** (a UUID).
4. **Events** (optional, for camera and doorbell alerts). Google-hosted
   topics stop on 30 November 2026, so use your own, in the same Google
   Cloud project:

   ```
   gcloud pubsub topics create nest-events --message-retention-duration=0s
   gcloud pubsub topics add-iam-policy-binding nest-events \
     --member="group:sdm-publisher@googlegroups.com" --role="roles/pubsub.publisher"
   gcloud pubsub subscriptions create nest-events-app --topic=nest-events
   ```

   Enter `projects/<cloud project>/topics/nest-events` as the Pub/Sub topic
   in the Device Access project. The app's field takes the subscription:
   `projects/<cloud project>/subscriptions/nest-events-app`.
5. **In the app**: turn on Google Nest (Settings › Integrations › Add
   integration), fill in the project ID, client ID and secret (and the
   subscription), press **Sign in with Google**. On Google's page choose the
   home and the devices to share. Google then lands on
   `https://www.google.com/?code=...`: copy that whole address into
   **Address Google sent you to** and press **Finish signing in**. The
   devices appear in their Google rooms.

To share other devices, sign in again. **Disconnect** forgets the sign-in
(the devices stay until removed in Settings › Devices).

## Google's side (for maintainers)

- Sign-in: `https://nestservices.google.com/partnerconnections/<project>/auth`
  with scopes `sdm.service` and `pubsub`; tokens from
  `https://www.googleapis.com/oauth2/v4/token` (access 1 hour; the refresh
  token lasts while it is used at least every 6 months).
- Devices: `GET /v1/enterprises/<project>/devices`; commands:
  `POST /v1/<device name>:executeCommand` (ThermostatMode.SetMode,
  ThermostatEco.SetMode, ThermostatTemperatureSetpoint.SetHeat/SetCool/
  SetRange, Fan.SetTimer).
- Events: Pub/Sub pull and acknowledge on the subscription. Only a thread's
  first message (STARTED) alerts, once per session; ones older than 10
  minutes (the server was off) only update the card.
