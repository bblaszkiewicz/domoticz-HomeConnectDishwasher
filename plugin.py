# -*- coding: utf-8 -*-
"""
<plugin key="HomeConnectDishwasher" name="Home Connect Dishwasher" author="custom"
        version="1.0.0" externallink="https://developer.home-connect.com">
    <description>
        Basic Bosch/Siemens/Neff dishwasher status monitoring through the Home Connect API.
        Uses OAuth Device Flow, so no inbound port forwarding is required.
    </description>
    <params>
        <param field="Mode1" label="Client ID" width="400px" required="true"/>
        <param field="Mode2" label="Client Secret" width="400px" required="true"
               password="true"/>
        <param field="Mode3" label="Dishwasher haId filter (empty = first found)"
               width="300px" required="false" default=""/>
        <param field="Mode6" label="Debug" width="100px">
            <options>
                <option label="Disabled" value="0" default="true"/>
                <option label="Enabled"  value="1"/>
            </options>
        </param>
    </params>
</plugin>
"""

import json
import os
import time
import traceback
 
try:
    import requests
except ImportError:
    requests = None
 
try:
    import Domoticz
    DOMOTICZ_AVAILABLE = True
except ImportError:
    # Test mode outside Domoticz.
    DOMOTICZ_AVAILABLE = False
 
# ---------------------------------------------------------------------------
# API constants
# ---------------------------------------------------------------------------
AUTH_BASE   = "https://api.home-connect.com/security/oauth"
API_BASE    = "https://api.home-connect.com/api"
SCOPE       = "IdentifyAppliance Dishwasher"
TOKEN_FILE  = "hc_dishwasher_tokens.json"
 
# Domoticz unit numbers
U_STATUS    = 1
U_DOOR      = 2
 
# Human-readable operation state labels
OPERATION_LABELS = {
    "BSH.Common.EnumType.OperationState.Inactive":       "Inactive",
    "BSH.Common.EnumType.OperationState.Ready":          "Ready",
    "BSH.Common.EnumType.OperationState.DelayedStart":   "Delayed start",
    "BSH.Common.EnumType.OperationState.Run":            "Running",
    "BSH.Common.EnumType.OperationState.Pause":          "Paused",
    "BSH.Common.EnumType.OperationState.ActionRequired": "Action required",
    "BSH.Common.EnumType.OperationState.Finished":       "Finished",
    "BSH.Common.EnumType.OperationState.Error":          "Error",
    "BSH.Common.EnumType.OperationState.Aborting":       "Aborting",
}

# ---------------------------------------------------------------------------
# Home Connect API helper
# ---------------------------------------------------------------------------
class HomeConnectAPI:
    def __init__(self, client_id, client_secret, token_path, log_fn, debug_fn):
        self.client_id     = client_id
        self.client_secret = client_secret
        self.token_path    = token_path
        self.log           = log_fn
        self.debug         = debug_fn
        self.access_token  = None
        self.refresh_token = None
        self.token_expiry  = 0
        self._load_tokens()
 
    # ------------------------------------------------------------------ tokens
    def _load_tokens(self):
        if os.path.exists(self.token_path):
            try:
                with open(self.token_path, "r") as f:
                    data = json.load(f)
                self.access_token  = data.get("access_token")
                self.refresh_token = data.get("refresh_token")
                self.token_expiry  = data.get("expiry", 0)
                self.debug("Tokens loaded from file.")
            except Exception as e:
                self.log("Error loading tokens: " + str(e))
 
    def _save_tokens(self, data):
        self.access_token  = data["access_token"]
        self.refresh_token = data.get("refresh_token", self.refresh_token)
        self.token_expiry  = time.time() + data.get("expires_in", 3600) - 60
        try:
            with open(self.token_path, "w") as f:
                json.dump({
                    "access_token":  self.access_token,
                    "refresh_token": self.refresh_token,
                    "expiry":        self.token_expiry,
                }, f)
            self.debug("Tokens saved.")
        except Exception as e:
            self.log("Error saving tokens: " + str(e))
 
    def has_tokens(self):
        return bool(self.access_token and self.refresh_token)

    def clear_tokens(self):
        self.access_token = None
        self.refresh_token = None
        self.token_expiry = 0
        try:
            if os.path.exists(self.token_path):
                os.remove(self.token_path)
                self.log("Old tokens removed.")
        except Exception as e:
            self.log("Error removing tokens: " + str(e))
        
    def _ensure_token(self):
        """Refresh the access token if it expired or is about to expire."""
        if time.time() >= self.token_expiry and self.refresh_token:
            self.debug("Refreshing access token...")
            try:
                r = requests.post(
                    AUTH_BASE + "/token",
                    data={
                        "grant_type":    "refresh_token",
                        "refresh_token": self.refresh_token,
                        "client_id":     self.client_id,
                        "client_secret": self.client_secret,
                    },
                    timeout=15,
                )
                r.raise_for_status()
                self._save_tokens(r.json())
                self.log("Token refreshed successfully.")
            except Exception as e:
                self.log("Error refreshing token: " + str(e))
                self.access_token = None
 
    # ----------------------------------------------------------- Device Flow
    def start_device_flow(self):
        """
        Start OAuth Device Flow and return the authorization payload.
        """
        r = requests.post(
            AUTH_BASE + "/device_authorization",
            data={
                "client_id": self.client_id,
                "scope":     SCOPE,
            },
            timeout=15,
        )
        r.raise_for_status()
        return r.json()
 
    def poll_device_flow(self, device_code):
        """
        Poll the token endpoint during Device Flow.
        Returns True when authorized, False while still pending.
        """
        r = requests.post(
            AUTH_BASE + "/token",
            data={
                "grant_type":  "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": device_code,
                "client_id":   self.client_id,
            },
            timeout=15,
        )
        data = r.json()
        error = data.get("error", "")
        if r.status_code == 200 and "access_token" in data:
            self._save_tokens(data)
            return True
        elif error in ("authorization_pending", "slow_down"):
            return False
        else:
            raise RuntimeError("Device Flow error: " + error + "  " + data.get("error_description", ""))
            
    # ------------------------------------------------------------ REST calls
    def _headers(self):
        return {
            "Authorization": "Bearer " + (self.access_token or ""),
            "Accept":        "application/vnd.bsh.sdk.v1+json",
        }
 
    def get(self, path, log_errors=True):
        self._ensure_token()
        r = requests.get(API_BASE + path, headers=self._headers(), timeout=15)
        if r.status_code == 401:
            # Try one forced refresh.
            self.token_expiry = 0
            self._ensure_token()
            r = requests.get(API_BASE + path, headers=self._headers(), timeout=15)
        if log_errors and r.status_code >= 400:
            self.log("API error {} for {}: {}".format(r.status_code, path, r.text[:500]))
        r.raise_for_status()
        return r.json()
 
    # --------------------------------------------------------- appliance helpers
    def get_appliances(self):
        data = self.get("/homeappliances")
        return data.get("data", {}).get("homeappliances", [])
 
    def find_dishwasher(self, haId_hint=""):
        appliances = self.get_appliances()
        for a in appliances:
            if a.get("type") == "Dishwasher":
                if not haId_hint or haId_hint.lower() in a.get("haId", "").lower():
                    return a
        return None
 
    def get_status(self, haId):
        """Return a key->value dictionary with appliance status values."""
        data = self.get("/homeappliances/{}/status".format(haId))
        result = {}
        for item in data.get("data", {}).get("status", []):
            result[item["key"]] = item.get("value")
        return result
            
# ---------------------------------------------------------------------------
# Domoticz plugin
# ---------------------------------------------------------------------------
class BasePlugin:
 
    def __init__(self):
        self.api         = None
        self.ha_id       = None
        self.token_path  = None
        self.heartbeat_n = 0
        # Device Flow state
        self.df_active      = False
        self.df_device_code = None
        self.df_interval    = 5
        self.df_expires     = 0
        self.df_next_poll   = 0
 
    # ----------------------------------------------------------------- helpers
    def _log(self, msg):
        if DOMOTICZ_AVAILABLE:
            Domoticz.Log(msg)
        else:
            print("[LOG]", msg)
 
    def _debug(self, msg):
        if DOMOTICZ_AVAILABLE:
            Domoticz.Debug(msg)
        else:
            print("[DBG]", msg)
 
    def _error(self, msg):
        if DOMOTICZ_AVAILABLE:
            Domoticz.Error(msg)
        else:
            print("[ERR]", msg)
 
    def _update(self, unit, n_value, s_value):
        if not DOMOTICZ_AVAILABLE:
            print("  UPDATE unit={}  nValue={}  sValue={}".format(unit, n_value, s_value))
            return
        if unit in Devices:
            Devices[unit].Update(nValue=n_value, sValue=str(s_value))
        else:
            self._error("Domoticz device unit {} does not exist.".format(unit))
 
    def _create_devices(self):
        if not DOMOTICZ_AVAILABLE:
            return
        if U_STATUS not in Devices:
            Domoticz.Device(Name="Dishwasher - Status",
                            Unit=U_STATUS, TypeName="Text", Used=1).Create()
        if U_DOOR not in Devices:
            Domoticz.Device(Name="Dishwasher - Door",
                            Unit=U_DOOR, TypeName="Contact", Used=1).Create()
                            
# --------------------------------------------------------------- lifecycle
    def onStart(self):
        if requests is None:
            self._error("Missing 'requests' library. Install it with: pip install requests")
            return
 
        if DOMOTICZ_AVAILABLE:
            debug_mode = Parameters.get("Mode6", "0")
            if debug_mode == "1":
                Domoticz.Debugging(1)
            client_id     = Parameters.get("Mode1", "").strip()
            client_secret = Parameters.get("Mode2", "").strip()
            ha_hint       = Parameters.get("Mode3", "").strip()
            home_folder   = Parameters.get("HomeFolder", "")
        else:
            # Test mode.
            client_id     = os.environ.get("HC_CLIENT_ID", "")
            client_secret = os.environ.get("HC_CLIENT_SECRET", "")
            ha_hint       = ""
            home_folder   = "./"
 
        if not client_id or not client_secret:
            self._error("Enter Client ID and Client Secret in the hardware settings.")
            return
 
        self.token_path = os.path.join(home_folder, TOKEN_FILE)
        self.api = HomeConnectAPI(
            client_id, client_secret, self.token_path,
            self._log, self._debug
        )
        self._create_devices()
        Domoticz.Heartbeat(10) if DOMOTICZ_AVAILABLE else None
 
        if self.api.has_tokens():
            self._log("Tokens found; looking for a dishwasher...")
            self._init_appliance(ha_hint)
        else:
            self._log("No tokens found; starting Device Flow authorization...")
            self._start_auth(ha_hint)
 
    def _start_auth(self, ha_hint=""):
        """Start Device Flow and log user instructions."""
        try:
            flow = self.api.start_device_flow()
        except Exception as e:
            self._error("Cannot start Device Flow: " + str(e))
            return
 
        self.df_active      = True
        self.df_device_code = flow["device_code"]
        self.df_interval    = flow.get("interval", 5)
        self.df_expires     = time.time() + flow.get("expires_in", 300)
        self.df_next_poll   = time.time() + self.df_interval
        self._ha_hint_pending = ha_hint
 
        uri  = flow.get("verification_uri_complete") or flow.get("verification_uri", "")
        code = flow.get("user_code", "")
 
        self._log("=" * 60)
        self._log("HOME CONNECT AUTHORIZATION REQUIRED")
        self._log("-" * 60)
        self._log("Open this link on any device:")
        self._log("  {}".format(uri))
        if code and "user_code" not in uri:
            self._log("If the page asks for a code, enter: {}".format(code))
        self._log("The plugin will keep polling for authorization automatically.")
        self._log("=" * 60)
 
    def _init_appliance(self, ha_hint=""):
        """Find the dishwasher and store its haId."""
        try:
            appliance = self.api.find_dishwasher(ha_hint)
            if not appliance:
                self._error(
                    "No dishwasher found in the Home Connect account. "
                    "Make sure the dishwasher is paired in the Home Connect app."
                )
                return
            self.ha_id = appliance["haId"]
            name       = appliance.get("name", self.ha_id)
            brand      = appliance.get("brand", "")
            self._log("Dishwasher found: {} {} ({})".format(brand, name, self.ha_id))
            # First refresh.
            self._refresh_data()
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 403:
                self._error(
                    "Missing API permissions. Removing the token and restarting authorization "
                    "with the required scope: {}.".format(SCOPE)
                )
                self.api.clear_tokens()
                self._start_auth(ha_hint)
                return
            self._error("Dishwasher initialization error: " + str(e))
            self._debug(traceback.format_exc())
        except Exception as e:
            self._error("Dishwasher initialization error: " + str(e))
            self._debug(traceback.format_exc())
 
    def onStop(self):
        self._log("Plugin stopped.")
 
    def onHeartbeat(self):
        self.heartbeat_n += 1
        
# ---- Device Flow polling ----
        if self.df_active:
            if time.time() >= self.df_expires:
                self._log("Authorization expired. Restarting Device Flow...")
                ha_hint = getattr(self, "_ha_hint_pending", "")
                self.df_active = False
                self._start_auth(ha_hint)
                return
            if time.time() >= self.df_next_poll:
                self.df_next_poll = time.time() + self.df_interval
                try:
                    ok = self.api.poll_device_flow(self.df_device_code)
                    if ok:
                        self.df_active = False
                        self._log("Authorization completed successfully.")
                        ha_hint = getattr(self, "_ha_hint_pending", "")
                        self._init_appliance(ha_hint)
                except RuntimeError as e:
                    self._error(str(e))
                    self.df_active = False
            return
 
        # ---- Normal API polling ----
        if not self.ha_id:
            return
        # Poll every ~30 seconds (heartbeat is 10 seconds).
        if self.heartbeat_n % 3 != 0:
            return
        try:
            self._refresh_data()
        except Exception as e:
            self._error("Data refresh error: " + str(e))
            self._debug(traceback.format_exc())
 
    def onCommand(self, Unit, Command, Level, Hue):
        self._debug("onCommand Unit={} Command={} Level={}".format(Unit, Command, Level))
        
# ----------------------------------------------------------------- data
    def _refresh_data(self):
        """Fetch API data and update Domoticz devices."""
        if not self.api or not self.ha_id:
            return
 
        status = self.api.get_status(self.ha_id)
 
        self._debug("Status: " + json.dumps(status))
 
        # ---- Operation status ----
        op_raw   = status.get("BSH.Common.Status.OperationState", "")
        op_label = OPERATION_LABELS.get(op_raw, op_raw.split(".")[-1] if op_raw else "Unknown")
        self._update(U_STATUS, 0, op_label)
 
        # ---- Door state ----
        door_raw = status.get("BSH.Common.Status.DoorState", "")
        door_open = 1 if "Open" in door_raw else 0
        self._update(U_DOOR, door_open, "Open" if door_open else "Closed")
            
# ---------------------------------------------------------------------------
# Required Domoticz module-level hooks
# ---------------------------------------------------------------------------
global _plugin
_plugin = BasePlugin()
 
def onStart():
    global _plugin
    _plugin.onStart()
 
def onStop():
    global _plugin
    _plugin.onStop()
 
def onHeartbeat():
    global _plugin
    _plugin.onHeartbeat()
 
def onCommand(Unit, Command, Level, Hue):
    global _plugin
    _plugin.onCommand(Unit, Command, Level, Hue)
