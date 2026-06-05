# Home Connect Dishwasher Plugin for Domoticz

A Domoticz plugin that monitors the status of a Bosch, Siemens, or Neff dishwasher through the Home Connect API.

The plugin uses the **OAuth 2.0 Device Authorization Flow**, which means:

* No local web server is required
* No port forwarding is required
* Works behind NAT and firewalls
* Authorization can be completed from any device with a web browser

## Features

* Dishwasher discovery through the Home Connect account
* Automatic OAuth token management
* Automatic token refresh
* Dishwasher operation state monitoring
* Dishwasher door state monitoring
* Optional filtering by appliance `haId`
* Debug logging support

## Requirements

* Domoticz
* Python `requests` library
* Home Connect Developer account
* Home Connect application registered in the Home Connect Developer Portal
* Dishwasher paired with the Home Connect mobile application

## Home Connect API Setup

1. Create a developer account at the Home Connect Developer Portal.

2. Create a new application.

3. Copy the generated:

   * Client ID
   * Client Secret

4. Configure the plugin in Domoticz using these credentials.

## Plugin Configuration

| Parameter              | Description                            |
| ---------------------- | -------------------------------------- |
| Client ID              | Home Connect application Client ID     |
| Client Secret          | Home Connect application Client Secret |
| Dishwasher haId filter | Optional appliance identifier filter   |
| Debug                  | Enable or disable debug logging        |

## Authorization

### Overview

The plugin uses the **OAuth 2.0 Device Authorization Grant (Device Flow)**.

Unlike traditional OAuth authorization, Device Flow does not require:

* Redirect URLs
* Local web servers
* Browser callbacks
* Inbound network connectivity

This makes it ideal for Domoticz installations running on Raspberry Pi, NAS systems, or servers without publicly accessible endpoints.

### First Startup

When the plugin starts for the first time, no access tokens are available.

The plugin automatically requests a Device Authorization Code from the Home Connect API and writes authorization instructions to the Domoticz log.

Example:

```text
============================================================
HOME CONNECT AUTHORIZATION REQUIRED
------------------------------------------------------------
Open this link on any device:
https://api.home-connect.com/security/oauth/device_user_action?user_code=XXXX-XXXX

The plugin will keep polling for authorization automatically.
============================================================
```

### User Authorization

1. Open the URL displayed in the Domoticz log.
2. Sign in with your Home Connect account.
3. Approve the requested permissions.
4. Return to Domoticz.

No additional action is required.

### Automatic Polling

While waiting for user approval, the plugin periodically polls the Home Connect OAuth endpoint.

Once authorization is completed:

1. Access token is received.
2. Refresh token is received.
3. Tokens are stored locally.
4. Dishwasher discovery starts automatically.

Example log message:

```text
Authorization completed successfully.
Dishwasher found: Bosch Dishwasher (SIEMENS-HCS01-XXXXXXXX)
```

## Token Storage

Tokens are stored in:

```text
hc_dishwasher_tokens.json
```

The file contains:

```json
{
  "access_token": "...",
  "refresh_token": "...",
  "expiry": 1234567890
}
```

The plugin automatically loads the file during startup.

## Token Refresh

Home Connect access tokens expire periodically.

The plugin automatically:

1. Detects token expiration.
2. Uses the refresh token.
3. Requests a new access token.
4. Updates the local token file.

No user interaction is required.

Example log message:

```text
Token refreshed successfully.
```

## Permission Recovery

If the Home Connect API returns a permission error (HTTP 403), the plugin automatically:

1. Removes stored tokens.
2. Starts a new Device Flow authorization.
3. Requests the required permissions again.

This allows recovery from changed API scopes or revoked authorizations.

## Devices Created

### Dishwasher - Status

Text device showing the current dishwasher operation state.

Possible values include:

* Inactive
* Ready
* Delayed start
* Running
* Paused
* Action required
* Finished
* Error
* Aborting

### Dishwasher - Door

Contact sensor representing the door state.

| State  | Value |
| ------ | ----- |
| Closed | 0     |
| Open   | 1     |

## Polling

The plugin polls the Home Connect API approximately every 30 seconds.

Status updates are reflected automatically in Domoticz.

## Troubleshooting

### "No dishwasher found"

Verify that:

* The appliance is paired in the Home Connect mobile application.
* The appliance belongs to the same Home Connect account used during authorization.
* The appliance type is supported as a dishwasher.

### "Missing API permissions"

The plugin will automatically restart the authorization process and request the required scopes again.

### Authorization expires before approval

The plugin automatically starts a new Device Flow session when the authorization window expires.

## License

MIT License
