/**
 * Smart home API client.
 *
 * The session lives in an HttpOnly cookie the browser sends automatically.
 * State-changing requests also send the csrf_token cookie's value in the
 * X-CSRF-Token header. Nothing is stored in the browser beyond those cookies.
 */

const API_BASE = '/api/v1';

class AuthError extends Error {}

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

const enc = encodeURIComponent;

class SmartHomeAPI {
  csrfToken() {
    const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/);
    return match ? decodeURIComponent(match[1]) : '';
  }

  async request(path, { method = 'GET', body } = {}) {
    const headers = { Accept: 'application/json' };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (method !== 'GET') headers['X-CSRF-Token'] = this.csrfToken();

    const response = await fetch(API_BASE + path, {
      method,
      headers,
      credentials: 'same-origin',
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = await response.json().catch(() => ({}));
    if (response.status === 401) throw new AuthError(data.detail || 'Not logged in');
    if (!response.ok) {
      const detail = Array.isArray(data.detail)
        ? data.detail.map((d) => String(d.msg).replace(/^Value error, /, '')).join('; ')
        : data.detail;
      throw new ApiError(detail || `Request failed (${response.status})`, response.status);
    }
    return data;
  }

  get(path) { return this.request(path); }
  post(path, body) { return this.request(path, { method: 'POST', body }); }
  put(path, body) { return this.request(path, { method: 'PUT', body }); }
  patch(path, body) { return this.request(path, { method: 'PATCH', body }); }
  del(path) { return this.request(path, { method: 'DELETE' }); }

  // Login and logout
  login(email, password, code, { keepLoggedIn = false, rememberMe = false, rememberDevice = false } = {}) {
    // 6 digits: authenticator code. 8 digits: one of the recovery codes.
    // Empty: the account has two-factor login turned off.
    const body = {
      email, password, keep_logged_in: keepLoggedIn, remember_me: rememberMe, remember_device: rememberDevice,
    };
    if (code.length === 8) body.recovery_code = code;
    else if (code) body.totp_code = code;
    // The name given in the "Name this device" popup (device-name.js).
    if (rememberDevice && this.deviceName) body.device_name = this.deviceName;
    return this.post('/auth/login', body);
  }
  logout() { return this.post('/auth/logout'); }
  getRememberedLogin() { return this.get('/auth/remembered'); }
  getLoginTimes() { return this.get('/admin/login-times'); }
  getLoginFailures() { return this.get('/admin/login-failures'); }
  setLoginFailures(body) { return this.put('/admin/login-failures', body); }
  setLoginTimes(body) { return this.put('/admin/login-times', body); }
  getMyDevices() { return this.get('/account/trusted-devices'); }
  forgetMyDevice(id) { return this.del(`/account/trusted-devices/${enc(id)}`); }
  renameMyDevice(id, name) { return this.patch(`/account/trusted-devices/${enc(id)}`, { name }); }
  getAllDevices() { return this.get('/admin/trusted-devices'); }
  forgetAnyDevice(id) { return this.del(`/admin/trusted-devices/${enc(id)}`); }
  getVerbose() { return this.get('/admin/verbose-logging'); }
  setVerbose(enabled) { return this.put('/admin/verbose-logging', { enabled }); }
  getGuestPage(homeId) { return this.get(`/homes/${enc(homeId)}/guest`); }
  getGuestAccess(homeId, userId) { return this.get(`/homes/${enc(homeId)}/members/${enc(userId)}/guest-access`); }
  setGuestAccess(homeId, userId, body) { return this.put(`/homes/${enc(homeId)}/members/${enc(userId)}/guest-access`, body); }
  getLayout(homeId) { return this.get(`/homes/${enc(homeId)}/layout`); }
  setLayout(homeId, roomOrder) { return this.put(`/homes/${enc(homeId)}/layout`, { room_order: roomOrder }); }

  // Devices
  getDevices(homeId) { return this.get(`/homes/${enc(homeId)}/devices`); }
  getDisplay(homeId) { return this.get(`/homes/${enc(homeId)}/display`); }
  setDisplay(homeId, show) { return this.put(`/homes/${enc(homeId)}/display`, { show_grouped_devices: show }); }
  getRooms(homeId) { return this.get(`/homes/${enc(homeId)}/rooms`); }
  createRoom(homeId, name) { return this.post(`/homes/${enc(homeId)}/rooms`, { name }); }
  deleteRoom(homeId, name) { return this.del(`/homes/${enc(homeId)}/rooms/${enc(name)}`); }
  setDeviceGroup(homeId, deviceId, groupId) { return this.put(`/homes/${enc(homeId)}/devices/${enc(deviceId)}/group`, { group_id: groupId }); }
  getGroups(homeId) { return this.get(`/homes/${enc(homeId)}/groups`); }
  createGroup(homeId, group) { return this.post(`/homes/${enc(homeId)}/groups`, group); }
  changeGroup(homeId, groupId, changes) { return this.patch(`/homes/${enc(homeId)}/groups/${enc(groupId)}`, changes); }
  deleteGroup(homeId, groupId) { return this.del(`/homes/${enc(homeId)}/groups/${enc(groupId)}`); }
  /** A group: each device's result; any that failed open the failure popup. */
  async groupCommand(homeId, groupId, command, payload) {
    const again = () => this.groupCommand(homeId, groupId, command, payload);
    let result;
    try {
      result = await this.post(`/homes/${enc(homeId)}/groups/${enc(groupId)}/command`, { command, payload });
    } catch (error) {
      this.commandFailed({ groupId, command, error, again });
      throw error;
    }
    const failed = (result.results || []).filter((r) => r.ok === false);
    if (failed.length) this.commandFailed({ groupId, command, failed, again });
    return result;
  }
  setDeviceLimits(homeId, deviceId, limits) { return this.put(`/homes/${enc(homeId)}/devices/${enc(deviceId)}/limits`, limits); }
  deleteDevice(homeId, deviceId) { return this.del(`/homes/${enc(homeId)}/devices/${enc(deviceId)}`); }
  updateDevice(homeId, deviceId, changes) {
    return this.patch(`/homes/${enc(homeId)}/devices/${enc(deviceId)}`, changes);
  }
  /** Guests send through the guest route, which checks their access. */
  async sendCommand(homeId, deviceId, command, payload = {}) {
    const path = this.guest ? `/homes/${enc(homeId)}/guest/devices/${enc(deviceId)}/command` : `/homes/${enc(homeId)}/devices/${enc(deviceId)}/command`;
    try {
      return await this.post(path, { command, payload });
    } catch (error) {
      this.commandFailed({ deviceId, command, error, again: () => this.sendCommand(homeId, deviceId, command, payload) });
      throw error;
    }
  }

  /** A device did not follow a command: the app shows a popup (app.js). */
  commandFailed(failure) {
    if (failure.error instanceof AuthError) return; // the login page takes over
    if (this.onCommandFailed) this.onCommandFailed(failure);
  }

  // Safety limits
  getSafetyLimits(homeId) { return this.get(`/homes/${enc(homeId)}/safety-limits`); }
  setSafetyLimits(homeId, deviceType, limits) {
    return this.put(`/homes/${enc(homeId)}/safety-limits/${enc(deviceType)}`, limits);
  }
  useRecommendedLimits(homeId) { return this.post(`/homes/${enc(homeId)}/safety-limits/recommended`); }

  // Integrations (device brands)
  getIntegrations(homeId) { return this.get(`/homes/${enc(homeId)}/integrations`); }
  getIntegrationProblems(homeId) { return this.get(`/homes/${enc(homeId)}/integrations/problems`); }
  setIntegration(homeId, id, enabled) { return this.put(`/homes/${enc(homeId)}/integrations/${enc(id)}`, { enabled }); }

  // Rheem EcoNet account (owner) and water-heater discovery (admin)
  getRheemAccount(homeId) { return this.get(`/homes/${enc(homeId)}/integrations/rheem_econet/account`); }
  saveRheemAccount(homeId, email, password) { return this.put(`/homes/${enc(homeId)}/integrations/rheem_econet/account`, { email, password }); }
  removeRheemAccount(homeId) { return this.del(`/homes/${enc(homeId)}/integrations/rheem_econet/account`); }
  syncRheem(homeId) { return this.post(`/homes/${enc(homeId)}/integrations/rheem_econet/sync`); }
  // GE Cync account (owner) and light and plug discovery (admin)
  getCyncAccount(homeId) { return this.get(`/homes/${enc(homeId)}/integrations/cync/account`); }
  saveCyncAccount(homeId, email, password, code) { return this.put(`/homes/${enc(homeId)}/integrations/cync/account`, code ? { email, password, code } : { email, password }); }
  removeCyncAccount(homeId) { return this.del(`/homes/${enc(homeId)}/integrations/cync/account`); }
  syncCync(homeId) { return this.post(`/homes/${enc(homeId)}/integrations/cync/sync`); }

  // Samsung TVs (admin)
  getTvs(homeId) { return this.get(`/homes/${enc(homeId)}/integrations/samsung_tv/tvs`); }
  addTv(homeId, tv) { return this.post(`/homes/${enc(homeId)}/integrations/samsung_tv/tvs`, tv); }
  editTv(homeId, deviceId, tv) { return this.put(`/homes/${enc(homeId)}/integrations/samsung_tv/tvs/${enc(deviceId)}`, tv); }
  pairTv(homeId, deviceId) { return this.post(`/homes/${enc(homeId)}/integrations/samsung_tv/tvs/${enc(deviceId)}/pair`); }
  sendTvPin(homeId, deviceId, pin) { return this.post(`/homes/${enc(homeId)}/integrations/samsung_tv/tvs/${enc(deviceId)}/pin`, { pin }); }
  removeTv(homeId, deviceId) { return this.del(`/homes/${enc(homeId)}/integrations/samsung_tv/tvs/${enc(deviceId)}`); }

  // Frigate: server settings (owner) and events (members)
  getFrigateServer(homeId) { return this.get(`/homes/${enc(homeId)}/integrations/frigate/server`); }
  saveFrigateServer(homeId, server) { return this.put(`/homes/${enc(homeId)}/integrations/frigate/server`, server); }
  removeFrigateServer(homeId) { return this.del(`/homes/${enc(homeId)}/integrations/frigate/server`); }
  getCameras(homeId) { return this.get(`/homes/${enc(homeId)}/cameras`); }
  getCameraEvents(homeId, camera = '') {
    const query = camera ? `&camera=${enc(camera)}` : '';
    return this.get(`/homes/${enc(homeId)}/cameras/events?limit=24${query}`);
  }

  // Activity log (owner only)
  getActivity(homeId, limit = 50) { return this.get(`/homes/${enc(homeId)}/audit?limit=${limit}`); }

  // Own account
  getAccount() { return this.get('/account'); }
  changePassword(currentPassword, newPassword) {
    return this.post('/account/password', { current_password: currentPassword, new_password: newPassword });
  }
  newRecoveryCodes(password) { return this.post('/account/recovery-codes', { password }); }
  startTotpReset(password) { return this.post('/account/totp/setup', { password }); }
  confirmTotpReset(code) { return this.post('/account/totp/confirm', { totp_code: code }); }
  getLoginOptions() { return this.get('/login-options'); }
  recover(login, code, newPassword) { return this.post('/recover', { login, code, new_password: newPassword }); }
  getLoginPolicy() { return this.get('/admin/login-policy'); }
  setLoginPolicy(policy) { return this.put('/admin/login-policy', policy); }
  getHttps() { return this.get('/admin/https'); }
  getEmailServer() { return this.get('/admin/email'); }
  saveEmailServer(server) { return this.put('/admin/email', server); }
  testEmailServer(to) { return this.post('/admin/email/test', { to }); }
  emailRecoveryCode(login) { return this.post('/recover/email', { login }); }
  setHttps(enabled) { return this.put('/admin/https', { enabled }); }
  saveHttpsCertificate(certificate, privateKey) { return this.put('/admin/https/certificate', { certificate, private_key: privateKey }); }
  deleteHttpsCertificate() { return this.del('/admin/https/certificate'); }
  renameHome(homeId, name) { return this.patch(`/homes/${enc(homeId)}`, { name }); }
  createUser(homeId, user) { return this.post(`/homes/${enc(homeId)}/members`, user); }
  setMemberPassword(homeId, userId, password) { return this.post(`/homes/${enc(homeId)}/members/${enc(userId)}/password`, { password }); }
  createResetCode(homeId, userId) { return this.post(`/homes/${enc(homeId)}/members/${enc(userId)}/reset-code`); }
  setPreferences(prefs) { return this.put('/account/preferences', prefs); }
  disableTotp(password, code) { return this.post('/account/totp/disable', { password, totp_code: code }); }
  getSecurityPolicy(homeId) { return this.get(`/homes/${enc(homeId)}/security`); }
  setSecurityPolicy(homeId, requireTwoFactor) { return this.put(`/homes/${enc(homeId)}/security`, { require_two_factor: requireTwoFactor }); }
  getSessions() { return this.get('/account/sessions'); }
  endSession(sessionId) { return this.del(`/account/sessions/${enc(sessionId)}`); }
  endOtherSessions() { return this.post('/account/sessions/revoke-others'); }

  // Household members
  getMembers(homeId) { return this.get(`/homes/${enc(homeId)}/members`); }
  changeRole(homeId, userId, role) { return this.patch(`/homes/${enc(homeId)}/members/${enc(userId)}`, { role }); }
  removeMember(homeId, userId) { return this.del(`/homes/${enc(homeId)}/members/${enc(userId)}`); }
  getMemberStatus(homeId) { return this.get(`/homes/${enc(homeId)}/members/status`); }
  setMemberActive(homeId, userId, active) { return this.put(`/homes/${enc(homeId)}/members/${enc(userId)}/active`, { active }); }
  createEnrollment(homeId, invite) { return this.post(`/homes/${enc(homeId)}/members/enrollments`, invite); }
  getEnrollments(homeId) { return this.get(`/homes/${enc(homeId)}/members/enrollments`); }
  cancelEnrollment(homeId, id) { return this.del(`/homes/${enc(homeId)}/members/enrollments/${enc(id)}`); }

  // Joining a home with an enrollment code (no session needed)
  startEnrollment(code) { return this.post('/enroll/start', { code }); }
  finishEnrollment(code, password, totpCode) {
    return this.post('/enroll/finish', { code, password, totp_code: totpCode || null });
  }
}

window.SmartHomeAPI = SmartHomeAPI;
window.AuthError = AuthError;
