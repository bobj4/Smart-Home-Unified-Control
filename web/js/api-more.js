/**
 * More of the API client (api.js stays under 300 lines): Schedules and
 * Scenes (automation.py). Guests allowed to run scenes use the guest routes.
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
});
