/**
 * More of the API client (api.js stays under 300 lines): Schedules and
 * Scenes (automation.py; guests allowed to run scenes use the guest
 * routes), and alerts (alerts.py: the home's settings, my choices, this
 * browser's notifications, and the bell's list).
 */

Object.assign(SmartHomeAPI.prototype, {
  getAutomation(homeId) {
    return this.get(`/homes/${enc(homeId)}/automation`);
  },
  saveScene(homeId, id, body) {
    return id ? this.put(`/homes/${enc(homeId)}/automation/scenes/${enc(id)}`, body) : this.post(`/homes/${enc(homeId)}/automation/scenes`, body);
  },
  deleteScene(homeId, id) {
    return this.del(`/homes/${enc(homeId)}/automation/scenes/${enc(id)}`);
  },
  runScene(homeId, id) {
    return this.post(this.guest ? `/homes/${enc(homeId)}/guest/scenes/${enc(id)}/run` : `/homes/${enc(homeId)}/automation/scenes/${enc(id)}/run`);
  },
  getHueScenes(homeId) {
    return this.get(`/homes/${enc(homeId)}/integrations/hue/scenes`);
  },
  getGuestScenes(homeId) {
    return this.get(`/homes/${enc(homeId)}/guest/scenes`);
  },
  saveSchedule(homeId, id, body) {
    return id ? this.put(`/homes/${enc(homeId)}/automation/schedules/${enc(id)}`, body) : this.post(`/homes/${enc(homeId)}/automation/schedules`, body);
  },
  deleteSchedule(homeId, id) {
    return this.del(`/homes/${enc(homeId)}/automation/schedules/${enc(id)}`);
  },
  runSchedule(homeId, id) {
    return this.post(`/homes/${enc(homeId)}/automation/schedules/${enc(id)}/run`);
  },
  setAutomationSettings(homeId, body) {
    return this.put(`/homes/${enc(homeId)}/automation/settings`, body);
  },
  getAlerts(homeId) {
    return this.get(`/homes/${enc(homeId)}/alerts`);
  },
  setAlertSettings(homeId, body) {
    return this.put(`/homes/${enc(homeId)}/alerts/settings`, body);
  },
  setMyAlerts(homeId, body) {
    return this.put(`/homes/${enc(homeId)}/alerts/mine`, body);
  },
  testAlert(homeId) {
    return this.post(`/homes/${enc(homeId)}/alerts/test`);
  },
  getPushKey() {
    return this.get('/account/push/key');
  },
  addPushDevice(body) {
    return this.post('/account/push', body);
  },
  removePushDevice(endpoint) {
    return this.post('/account/push/remove', { endpoint });
  },
  getAlertFeed(homeId) {
    return this.get(`/homes/${enc(homeId)}/alerts/feed`);
  },
  markAlertsSeen(homeId) {
    return this.post(`/homes/${enc(homeId)}/alerts/feed/seen`);
  },
  setInputNames(homeId, deviceId, names) {
    return this.put(`/homes/${enc(homeId)}/devices/${enc(deviceId)}/input-names`, { names });
  },
  dismissAllAlerts(homeId) {
    return this.del(`/homes/${enc(homeId)}/alerts/feed`);
  },
  dismissAlert(homeId, itemId) {
    return this.del(`/homes/${enc(homeId)}/alerts/feed/${enc(itemId)}`);
  },
  getDeviceAlerts(homeId) {
    return this.get(`/homes/${enc(homeId)}/alerts/devices`);
  },
  setDeviceAlerts(homeId, deviceId, body) {
    return this.put(`/homes/${enc(homeId)}/alerts/devices/${enc(deviceId)}`, body);
  },
  locateFromAddress(homeId) {
    return this.post(`/homes/${enc(homeId)}/automation/settings/locate`);
  },
});
