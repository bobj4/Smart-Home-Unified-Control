# Known Issues

- **Wake-on-LAN inside Docker on Windows**: Wake-on-LAN cannot reach TVs when the app runs inside Docker on Windows. This is a Windows Docker networking limitation; connect the app directly on Windows instead.

- **Self-signed HTTPS certificate warning**: When HTTPS is enabled, each device shows a browser warning about the self-signed certificate. Click "Advanced" and then "Proceed" to accept the certificate for that site.

- **HTTPS requires a server restart**: After changing HTTPS settings, the server must be restarted for the change to take effect. Restart the Docker container or the uvicorn process.

- **2014-2015 TV protocol tested against a fake TV**: The encrypted remote protocol for Samsung 2014-2015 (H and J series) TVs has only been tested against a fake TV; real-world performance is unverified.
