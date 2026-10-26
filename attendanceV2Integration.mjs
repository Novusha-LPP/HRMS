/**
 * ==============================================================================
 * ATTENDANCE V2 & HRMS STANDALONE INTEGRATION MODULE
 * ==============================================================================
 * 
 * A self-contained, enterprise-grade drop-in integration file for Express.js
 * that provides full Attendance, Biometric & Web Punch, Leave Management,
 * Regularization, Approvals, Staff Directory, and Admin Overrides powered by HRMS.
 * 
 * Features Included:
 * 1. Built-in HRMS Client with automatic session issuance & cache
 * 2. Self-healing auto-linking for employees by code, username, or email
 * 3. Live Web Punch terminal with GPS geolocation support
 * 4. Monthly Attendance Ledger with calendar & overtime breakdown
 * 5. Leave Quota Balances & Leave Application workflows
 * 6. Attendance Correction & Regularization requests
 * 7. Manager & HR Approvals Inbox (decision workflow)
 * 8. Workforce Directory merging local application users with HRMS profiles
 * 9. Direct 1-Click Admin Attendance overrides (Present, Absent, Half Day)
 * 10. Offline resilience handling with standard HTTP 503 codes
 * 
 * QUICK START:
 * ```javascript
 * import express from 'express';
 * import { createAttendanceV2Router } from './attendanceV2Integration.mjs';
 * 
 * const app = express();
 * app.use(express.json());
 * 
 * // Mount the entire Attendance V2 feature suite with 1 line:
 * app.use('/api/attendance/v2', createAttendanceV2Router({
 *   hrmsBaseUrl: process.env.HRMS_BASE_URL || 'http://hrmsapi.alvision.in',
 *   hrmsApiKey: process.env.HRMS_API_KEY || 'your_hrms_integration_key',
 * }));
 * ```
 */

import express from 'express';

// ─── 1. STANDALONE HRMS INTEGRATION CLIENT ────────────────────────────────────

export class StandaloneHrmsClient {
  constructor(config = {}) {
    this.baseUrl = (config.hrmsBaseUrl || process.env.HRMS_BASE_URL || 'http://hrmsapi.alvision.in').replace(/\/$/, '');
    this.apiKey = config.hrmsApiKey || process.env.HRMS_API_KEY || 'hrms_test_i50hhHYx_KuXYvGMeJOk76AzvIapcmWKg5wvNIyKxDFaax1fQ';
    
    // In-memory cache for issued employee session tokens
    this.sessionCache = new Map();

    // Cache of integration employees list
    this.employeesCache = null;
    this.employeesCachedAt = 0;
    this.CACHE_TTL = 10 * 60 * 1000; // 10 minutes
  }

  /**
   * Helper for integration endpoints using X-API-Key header.
   */
  async integrationRequest(path, options = {}) {
    const headers = {
      'Accept': 'application/json',
      'X-API-Key': this.apiKey,
      ...(options.headers || {}),
    };

    if (options.body && typeof options.body === 'object' && !(options.body instanceof FormData)) {
      headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(options.body);
    }

    const url = `${this.baseUrl}${path}`;
    const timeoutMs = options.timeoutMs || 15000;
    const signal = options.signal || AbortSignal.timeout(timeoutMs);

    let res;
    try {
      res = await fetch(url, { ...options, headers, signal });
    } catch (fetchErr) {
      const err = new Error(fetchErr.name === 'TimeoutError' || fetchErr.name === 'AbortError'
        ? `HRMS request timed out after ${timeoutMs / 1000}s`
        : `HRMS connection failed: ${fetchErr.message}`);
      err.code = fetchErr.code || (fetchErr.name === 'TimeoutError' ? 'ETIMEDOUT' : 'HRMS_NETWORK_ERROR');
      err.status = 503;
      throw err;
    }

    if (!res.ok) {
      const errorJson = await res.json().catch(() => null);
      const detail = errorJson?.detail || errorJson?.error?.message || errorJson?.message || `HRMS integration error ${res.status}`;
      const err = new Error(detail);
      err.status = res.status;
      err.code = errorJson?.code;
      err.details = errorJson?.error?.details || [];
      throw err;
    }

    if (res.status === 204) return null;
    return await res.json();
  }

  /**
   * Helper for standard HRMS endpoints using Bearer token.
   */
  async bearerRequest(path, token, options = {}) {
    const headers = {
      'Accept': 'application/json',
      'Authorization': `Bearer ${token}`,
      ...(options.headers || {}),
    };

    if (options.body && typeof options.body === 'object' && !(options.body instanceof FormData)) {
      headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(options.body);
    }

    const url = `${this.baseUrl}${path}`;
    const timeoutMs = options.timeoutMs || 15000;
    const signal = options.signal || AbortSignal.timeout(timeoutMs);

    let res;
    try {
      res = await fetch(url, { ...options, headers, signal });
    } catch (fetchErr) {
      const err = new Error(fetchErr.name === 'TimeoutError' || fetchErr.name === 'AbortError'
        ? `HRMS request timed out after ${timeoutMs / 1000}s`
        : `HRMS connection failed: ${fetchErr.message}`);
      err.code = fetchErr.code || (fetchErr.name === 'TimeoutError' ? 'ETIMEDOUT' : 'HRMS_NETWORK_ERROR');
      err.status = 503;
      throw err;
    }

    if (!res.ok) {
      if (res.status === 401 && options.userId) {
        this.sessionCache.delete(String(options.userId));
      }
      const errorJson = await res.json().catch(() => null);
      const detail = errorJson?.detail || errorJson?.error?.message || errorJson?.message || `HRMS error ${res.status}`;
      const err = new Error(detail);
      err.status = res.status;
      err.code = errorJson?.code;
      err.details = errorJson?.error?.details || [];
      throw err;
    }

    if (res.status === 204) return null;
    return await res.json();
  }

  /**
   * Fetch all employees from the integration feed with pagination.
   */
  async getIntegrationEmployees(forceRefresh = false) {
    const now = Date.now();
    if (!forceRefresh && this.employeesCache && this.employeesCachedAt > now - this.CACHE_TTL) {
      return this.employeesCache;
    }

    let allEmployees = [];
    let offset = 0;
    const limit = 200;
    let pageCount = 0;
    const MAX_PAGES = 50;

    while (true) {
      const res = await this.integrationRequest(`/v1/integrations/employees?limit=${limit}&offset=${offset}`);
      const emps = res?.employees || [];
      allEmployees.push(...emps);
      pageCount++;
      if (emps.length < limit || !res?.has_more || pageCount >= MAX_PAGES) break;
      offset += limit;
    }

    this.employeesCache = allEmployees;
    this.employeesCachedAt = now;
    return allEmployees;
  }

  /**
   * Helper: Formats a local application user object into the standard HRMS integration payload.
   */
  formatUserForHrms(user = {}) {
    const rawHireDate = user.date_of_joining || user.joining_date || user.hire_date;
    let hireDateStr = '2024-01-01';
    if (rawHireDate) {
      const d = new Date(rawHireDate);
      if (!isNaN(d.getTime())) hireDateStr = d.toISOString().split('T')[0];
    }
    const isManager = ['ADMIN', 'MANAGER', 'HOD', 'HEAD_OF_DEPARTMENT'].includes(String(user.role || '').toUpperCase());

    return {
      employee_code: (user.employee_code || user.employeeCode || user.username || '').trim(),
      first_name: (user.first_name || user.firstName || user.name || 'Employee').trim(),
      last_name: (user.last_name || user.lastName || '').trim() || '.',
      email: (user.email || '').trim() || null,
      mobile: (user.mobile || user.phone || '').trim() || null,
      company: user.company || 'Suraj Forwarders Private Limited',
      department: user.department || 'Operations',
      designation: user.designation || 'Executive',
      location: user.branch || user.location || 'Head Office',
      role: isManager ? 'MANAGER' : 'EMPLOYEE',
      hire_date: hireDateStr,
      source_updated_at: new Date().toISOString(),
    };
  }

  /**
   * Auto-Sync Onboarding: Upserts a new or existing employee directly into HRMS.
   */
  async upsertEmployee(externalId, employeeData, options = {}) {
    const query = options.dryRun ? '?dry_run=true' : '';
    const headers = {};
    if (options.idempotencyKey) {
      headers['Idempotency-Key'] = options.idempotencyKey;
    }
    const res = await this.integrationRequest(`/v1/integrations/employees/${encodeURIComponent(externalId)}${query}`, {
      method: 'PUT',
      headers,
      body: employeeData,
    });
    // Invalidate employee feed cache so new hire appears immediately
    this.employeesCache = null;
    this.employeesCachedAt = 0;
    this.sessionCache.delete(String(externalId));
    return res;
  }

  /**
   * Self-healing: Links a local application user to an HRMS employment record.
   */
  async linkUserToHrms(user) {
    const externalId = String(user._id || user.id);
    const emps = await this.getIntegrationEmployees(true);

    const norm = (val) => String(val || '').trim().toLowerCase();
    const cleanAlphaNum = (val) => String(val || '').toLowerCase().replace(/[^a-z0-9]/g, '');

    const targetUsername = norm(user.username);
    const targetCleanUsername = cleanAlphaNum(user.username);
    const targetCode = norm(user.employee_code || user.employeeCode);
    const targetCleanCode = cleanAlphaNum(user.employee_code || user.employeeCode);
    const targetEmail = norm(user.email);
    const targetFullName = norm(`${user.first_name || ''} ${user.last_name || ''}`).trim();

    const match = emps.find((e) => {
      const code = norm(e.employee_code);
      const cleanCode = cleanAlphaNum(e.employee_code);
      const email = norm(e.email);
      const empFullName = norm(`${e.first_name || e.legal_first_name || ''} ${e.last_name || e.legal_last_name || ''}`).trim();

      if (targetCode && (code === targetCode || cleanCode === targetCleanCode)) return true;
      if (targetUsername && (code === targetUsername || cleanCode === targetCleanUsername)) return true;
      if (targetEmail && email === targetEmail) return true;
      if (targetFullName && empFullName && targetFullName === empFullName && targetFullName.length > 5) return true;

      return false;
    });

    if (match && match.employment_id) {
      try {
        await this.integrationRequest(`/v1/integrations/employees/${encodeURIComponent(externalId)}`, {
          method: 'PUT',
          body: { employment_id: match.employment_id },
        });
      } catch (e) {
        console.warn(`[HRMS Integration] Linking external_id PUT notice:`, e.message);
      }

      this.sessionCache.delete(externalId);
      return match;
    }

    return null;
  }

  /**
   * Obtains a delegated session token for an employee.
   */
  async getEmployeeSession(user) {
    if (!user || (!user._id && !user.id)) {
      throw new Error('User context is required to issue HRMS session');
    }

    const externalId = String(user._id || user.id);
    const now = Date.now();
    const cached = this.sessionCache.get(externalId);

    if (cached && cached.expiresAt > now + 60 * 1000) {
      return cached;
    }

    try {
      const data = await this.integrationRequest('/v1/integrations/sessions', {
        method: 'POST',
        body: { external_id: externalId },
      });

      const sessionObj = {
        access_token: data.access_token,
        employment_id: data.employment_id,
        roles: data.roles || ['EMPLOYEE'],
        expiresAt: now + (data.expires_in || 3600) * 1000,
      };

      this.sessionCache.set(externalId, sessionObj);
      return sessionObj;
    } catch (err) {
      if (err.status === 403 || err.code === 'SESSION_REFUSED') {
        const linked = await this.linkUserToHrms(user);
        if (linked) {
          const data = await this.integrationRequest('/v1/integrations/sessions', {
            method: 'POST',
            body: { external_id: externalId },
          });

          const sessionObj = {
            access_token: data.access_token,
            employment_id: data.employment_id,
            roles: data.roles || ['EMPLOYEE'],
            expiresAt: now + (data.expires_in || 3600) * 1000,
          };

          this.sessionCache.set(externalId, sessionObj);
          return sessionObj;
        }
      }

      throw err;
    }
  }

  // ─── Self-Service Endpoints ───────────────────────────────────────────────

  async getTodayStatus(user, workDate = null) {
    const session = await this.getEmployeeSession(user);
    const query = workDate ? `?work_date=${encodeURIComponent(workDate)}` : '';
    return await this.bearerRequest(`/v1/time/today${query}`, session.access_token, { userId: user._id || user.id });
  }

  async recordPunch({ user, punchType, source = 'WEB', latitude = null, longitude = null, confirmLongDay = false }) {
    const session = await this.getEmployeeSession(user);
    const body = {
      punch_type: punchType,
      source: source || 'WEB',
      latitude: latitude ? Number(latitude) : null,
      longitude: longitude ? Number(longitude) : null,
      confirm_long_day: Boolean(confirmLongDay),
    };
    return await this.bearerRequest('/v1/time/punches', session.access_token, {
      method: 'POST',
      body,
      userId: user._id || user.id,
    });
  }

  async getAttendanceDays({ user, fromDate, toDate }) {
    const session = await this.getEmployeeSession(user);
    const params = new URLSearchParams({ from_date: fromDate, to_date: toDate });
    return await this.bearerRequest(`/v1/time/attendance-days?${params.toString()}`, session.access_token, { userId: user._id || user.id });
  }

  async getLeaveBalances(user, year = null) {
    const session = await this.getEmployeeSession(user);
    const query = year ? `?year=${encodeURIComponent(year)}` : '';
    return await this.bearerRequest(`/v1/leave/balances${query}`, session.access_token, { userId: user._id || user.id });
  }

  async getLeaveTypes(user) {
    const session = await this.getEmployeeSession(user);
    return await this.bearerRequest('/v1/leave/types', session.access_token, { userId: user._id || user.id });
  }

  async getLeaveApplications(user, status = null) {
    const session = await this.getEmployeeSession(user);
    const query = status ? `?status=${encodeURIComponent(status)}` : '';
    return await this.bearerRequest(`/v1/leave/applications${query}`, session.access_token, { userId: user._id || user.id });
  }

  async applyLeave({ user, leaveTypeId, fromDate, toDate, halfDayOption = 'NONE', reason = '' }) {
    const session = await this.getEmployeeSession(user);
    const draft = await this.bearerRequest('/v1/leave/applications', session.access_token, {
      method: 'POST',
      body: {
        leave_type_id: leaveTypeId,
        from_date: fromDate,
        to_date: toDate,
        half_day_option: halfDayOption || 'NONE',
        reason: reason || null,
      },
      userId: user._id || user.id,
    });

    if (draft && draft.id) {
      return await this.bearerRequest(`/v1/leave/applications/${encodeURIComponent(draft.id)}/submit`, session.access_token, {
        method: 'POST',
        userId: user._id || user.id,
      });
    }

    return draft;
  }

  async cancelLeave({ user, applicationId, cancelReason = 'Cancelled by employee' }) {
    const session = await this.getEmployeeSession(user);
    return await this.bearerRequest(`/v1/leave/applications/${encodeURIComponent(applicationId)}/cancel`, session.access_token, {
      method: 'POST',
      body: { cancel_reason: cancelReason || null },
      userId: user._id || user.id,
    });
  }

  async getCorrections(user, status = null) {
    const session = await this.getEmployeeSession(user);
    const query = status ? `?status=${encodeURIComponent(status)}` : '';
    return await this.bearerRequest(`/v1/corrections${query}`, session.access_token, { userId: user._id || user.id });
  }

  async requestCorrection({ user, workDate, correctionType, requestedPunchIn = null, requestedPunchOut = null, reason }) {
    const session = await this.getEmployeeSession(user);
    return await this.bearerRequest('/v1/corrections', session.access_token, {
      method: 'POST',
      body: {
        work_date: workDate,
        correction_type: correctionType,
        requested_punch_in: requestedPunchIn || null,
        requested_punch_out: requestedPunchOut || null,
        reason: reason || 'Attendance correction',
      },
      userId: user._id || user.id,
    });
  }

  async cancelCorrection({ user, correctionId }) {
    const session = await this.getEmployeeSession(user);
    return await this.bearerRequest(`/v1/corrections/${encodeURIComponent(correctionId)}/cancel`, session.access_token, {
      method: 'POST',
      userId: user._id || user.id,
    });
  }

  async approveCorrection({ user, correctionId, comments = 'Approved by administrator' }) {
    const session = await this.getEmployeeSession(user);
    return await this.bearerRequest(`/v1/corrections/${encodeURIComponent(correctionId)}/approve`, session.access_token, {
      method: 'POST',
      body: { action: 'APPROVE', comments: comments || null },
      userId: user._id || user.id,
    });
  }

  async getApprovalsInbox(user) {
    const session = await this.getEmployeeSession(user);
    return await this.bearerRequest('/v1/approvals/inbox', session.access_token, { userId: user._id || user.id });
  }

  async makeApprovalDecision({ user, instanceId, action, comments = '' }) {
    const session = await this.getEmployeeSession(user);
    return await this.bearerRequest(`/v1/approvals/requests/${encodeURIComponent(instanceId)}/decision`, session.access_token, {
      method: 'POST',
      body: {
        action: action === 'REJECT' ? 'REJECT' : 'APPROVE',
        comments: comments || null,
      },
      userId: user._id || user.id,
    });
  }
}

// ─── 2. EXPRESS ROUTER FACTORY ───────────────────────────────────────────────

/**
 * Creates and returns an Express Router with all Attendance V2 endpoints.
 * 
 * @param {Object} options Configuration options
 * @param {string} [options.hrmsBaseUrl] HRMS Base API URL
 * @param {string} [options.hrmsApiKey] HRMS Integration API Key
 * @param {Function} [options.authMiddleware] Middleware setting req.user
 * @param {Function} [options.findUserById] Async function (userId) => user object
 * @param {Function} [options.findUsers] Async function () => array of local user objects
 * @param {Function} [options.onAttendanceUpsert] Async hook (record) => void
 * @param {Function} [options.isAdmin] Function (user) => boolean
 */
export function createAttendanceV2Router(options = {}) {
  const router = express.Router();
  const hrmsClient = new StandaloneHrmsClient(options);

  // Authentication Guard Middleware
  if (typeof options.authMiddleware === 'function') {
    router.use(options.authMiddleware);
  } else {
    // Default fallback auth guard
    router.use((req, res, next) => {
      if (!req.user) {
        return res.status(401).json({ message: 'Authentication required for Attendance V2' });
      }
      next();
    });
  }

  const isAdminUser = (user) => {
    if (typeof options.isAdmin === 'function') return options.isAdmin(user);
    return user?.role === 'Admin' || user?.role === 'HR' || user?.isHod === true;
  };

  const handleHrmsError = (res, err, defaultMsg = 'HRMS Operation Failed') => {
    const isOffline =
      err.status === 530 ||
      err.status === 502 ||
      err.status === 503 ||
      err.status === 504 ||
      err.name === 'AbortError' ||
      err.name === 'TimeoutError' ||
      err.code === 'ECONNREFUSED' ||
      err.code === 'ENOTFOUND' ||
      err.code === 'ETIMEDOUT' ||
      err.code === 'HRMS_NETWORK_ERROR' ||
      (err.message && (
        String(err.message).includes('1033') ||
        String(err.message).includes('530') ||
        String(err.message).includes('fetch failed') ||
        String(err.message).includes('timed out')
      ));

    const statusCode = isOffline ? 503 : (err.status || 500);
    const message = isOffline
      ? 'HRMS Platform API is currently offline or unreachable. Please try again in a moment.'
      : (err.message || defaultMsg);

    return res.status(statusCode).json({
      message,
      code: isOffline ? 'HRMS_SERVICE_OFFLINE' : (err.code || 'HRMS_ERROR'),
      details: err.details || [],
    });
  };

  // Helper to resolve target user (for admin on-behalf operations)
  const resolveTargetUser = async (req) => {
    const targetUserId = req.query.user_id || req.body?.user_id;
    if (targetUserId && isAdminUser(req.user)) {
      if (typeof options.findUserById === 'function') {
        const u = await options.findUserById(targetUserId);
        if (u) return u;
      }
      return { _id: targetUserId, id: targetUserId, username: 'target_employee' };
    }
    return req.user;
  };

  // ─── CORE ATTENDANCE ROUTES ───────────────────────────────────────────────

  /**
   * GET /session
   * Profile status, employment mapping, and HRMS session tokens
   */
  router.get('/session', async (req, res) => {
    try {
      const session = await hrmsClient.getEmployeeSession(req.user);
      return res.json({
        user: {
          id: req.user._id || req.user.id,
          username: req.user.username,
          name: `${req.user.first_name || ''} ${req.user.last_name || ''}`.trim() || req.user.username,
          role: req.user.role || 'User',
          company: req.user.company,
          department: req.user.department,
        },
        hrms: {
          employment_id: session.employment_id,
          roles: session.roles,
        },
      });
    } catch (err) {
      if (err.status === 403 || err.code === 'SESSION_REFUSED') {
        return res.json({
          unlinked: true,
          message: 'User is not yet linked to an active HRMS employment record',
          user: req.user,
        });
      }
      return handleHrmsError(res, err, 'Failed to establish HRMS session');
    }
  });

  /**
   * GET /today
   * Live punch status, chronograph elapsed time, active state
   */
  router.get('/today', async (req, res) => {
    try {
      const user = await resolveTargetUser(req);
      const data = await hrmsClient.getTodayStatus(user, req.query.work_date);
      return res.json(data);
    } catch (err) {
      return handleHrmsError(res, err, 'Failed to fetch today attendance status');
    }
  });

  /**
   * POST /punch
   * Record punch in/out/break
   */
  router.post('/punch', async (req, res) => {
    try {
      const { punch_type, source, latitude, longitude, confirm_long_day } = req.body;
      if (!punch_type) {
        return res.status(400).json({ message: 'punch_type is required (IN, OUT, BREAK_START, BREAK_END)' });
      }

      const result = await hrmsClient.recordPunch({
        user: req.user,
        punchType: punch_type,
        source: source || 'WEB',
        latitude,
        longitude,
        confirmLongDay: confirm_long_day,
      });

      return res.json(result);
    } catch (err) {
      return handleHrmsError(res, err, 'Failed to record punch');
    }
  });

  /**
   * GET /days
   * Monthly attendance ledger records
   */
  router.get('/days', async (req, res) => {
    try {
      const { from_date, to_date } = req.query;
      if (!from_date || !to_date) {
        return res.status(400).json({ message: 'from_date and to_date query parameters are required' });
      }

      const user = await resolveTargetUser(req);
      const data = await hrmsClient.getAttendanceDays({
        user,
        fromDate: from_date,
        toDate: to_date,
      });

      return res.json(data);
    } catch (err) {
      return handleHrmsError(res, err, 'Failed to fetch attendance ledger');
    }
  });

  // ─── LEAVE MANAGEMENT ROUTES ──────────────────────────────────────────────

  router.get('/leave/types', async (req, res) => {
    try {
      const user = await resolveTargetUser(req);
      const data = await hrmsClient.getLeaveTypes(user);
      return res.json(data);
    } catch (err) {
      return handleHrmsError(res, err, 'Failed to fetch leave types');
    }
  });

  router.get('/leave/balances', async (req, res) => {
    try {
      const user = await resolveTargetUser(req);
      const data = await hrmsClient.getLeaveBalances(user, req.query.year);
      return res.json(data);
    } catch (err) {
      return handleHrmsError(res, err, 'Failed to fetch leave balances');
    }
  });

  router.get('/leave/applications', async (req, res) => {
    try {
      const user = await resolveTargetUser(req);
      const data = await hrmsClient.getLeaveApplications(user, req.query.status);
      return res.json(data);
    } catch (err) {
      return handleHrmsError(res, err, 'Failed to fetch leave applications');
    }
  });

  router.post('/leave/apply', async (req, res) => {
    try {
      const { leave_type_id, from_date, to_date, half_day_option, reason } = req.body;
      if (!leave_type_id || !from_date || !to_date) {
        return res.status(400).json({ message: 'leave_type_id, from_date, and to_date are required' });
      }

      const user = await resolveTargetUser(req);
      const result = await hrmsClient.applyLeave({
        user,
        leaveTypeId: leave_type_id,
        fromDate: from_date,
        toDate: to_date,
        halfDayOption: half_day_option || 'NONE',
        reason: reason || '',
      });

      return res.json(result);
    } catch (err) {
      return handleHrmsError(res, err, 'Failed to submit leave application');
    }
  });

  router.delete('/leave/applications/:id', async (req, res) => {
    try {
      const user = await resolveTargetUser(req);
      const result = await hrmsClient.cancelLeave({
        user,
        applicationId: req.params.id,
        cancelReason: req.body?.cancel_reason || 'Cancelled by user',
      });
      return res.json(result);
    } catch (err) {
      return handleHrmsError(res, err, 'Failed to cancel leave application');
    }
  });

  // ─── ATTENDANCE CORRECTIONS (REGULARIZATION) ──────────────────────────────

  router.get('/corrections', async (req, res) => {
    try {
      const user = await resolveTargetUser(req);
      const data = await hrmsClient.getCorrections(user, req.query.status);
      return res.json(data);
    } catch (err) {
      return handleHrmsError(res, err, 'Failed to fetch correction requests');
    }
  });

  router.post('/corrections/request', async (req, res) => {
    try {
      const { work_date, correction_type, requested_punch_in, requested_punch_out, reason } = req.body;
      if (!work_date || !correction_type || !reason) {
        return res.status(400).json({ message: 'work_date, correction_type, and reason are required' });
      }

      const user = await resolveTargetUser(req);
      const result = await hrmsClient.requestCorrection({
        user,
        workDate: work_date,
        correctionType: correction_type,
        requestedPunchIn: requested_punch_in,
        requestedPunchOut: requested_punch_out,
        reason,
      });

      return res.json(result);
    } catch (err) {
      return handleHrmsError(res, err, 'Failed to submit correction request');
    }
  });

  router.delete('/corrections/:id', async (req, res) => {
    try {
      const user = await resolveTargetUser(req);
      const result = await hrmsClient.cancelCorrection({
        user,
        correctionId: req.params.id,
      });
      return res.json(result);
    } catch (err) {
      return handleHrmsError(res, err, 'Failed to cancel correction request');
    }
  });

  // ─── APPROVALS INBOX (MANAGERS & ADMINS) ──────────────────────────────────

  router.get('/approvals/inbox', async (req, res) => {
    try {
      const data = await hrmsClient.getApprovalsInbox(req.user);
      return res.json(data);
    } catch (err) {
      return handleHrmsError(res, err, 'Failed to fetch approvals inbox');
    }
  });

  router.post('/approvals/action', async (req, res) => {
    try {
      const { instance_id, action, comments } = req.body;
      if (!instance_id || !action) {
        return res.status(400).json({ message: 'instance_id and action (APPROVE or REJECT) are required' });
      }

      const result = await hrmsClient.makeApprovalDecision({
        user: req.user,
        instanceId: instance_id,
        action,
        comments,
      });

      return res.json(result);
    } catch (err) {
      return handleHrmsError(res, err, 'Failed to process approval decision');
    }
  });

  // ─── WORKFORCE DIRECTORY & ADMIN OVERRIDES ────────────────────────────────

  /**
   * GET /employees
   * Merges active local users with HRMS employment profiles
   */
  router.get('/employees', async (req, res) => {
    try {
      if (!isAdminUser(req.user)) {
        return res.status(403).json({ message: 'Permission denied: Requires Admin or HOD role' });
      }

      const forceRefresh = req.query.refresh === 'true';
      let localUsers = [];
      if (typeof options.findUsers === 'function') {
        localUsers = await options.findUsers();
      }

      const hrmsEmps = await hrmsClient.getIntegrationEmployees(forceRefresh);
      const hrmsMapByCode = new Map();
      const hrmsMapByExtId = new Map();
      const hrmsMapByEmail = new Map();

      for (const e of hrmsEmps) {
        if (e.employee_code) hrmsMapByCode.set(String(e.employee_code).toLowerCase().trim(), e);
        if (e.external_id) hrmsMapByExtId.set(String(e.external_id).trim(), e);
        if (e.email) hrmsMapByEmail.set(String(e.email).toLowerCase().trim(), e);
      }

      const employeesList = (localUsers || []).map((u) => {
        const uId = String(u._id || u.id);
        const code = String(u.employee_code || u.employeeCode || u.username || '').toLowerCase().trim();
        const email = String(u.email || '').toLowerCase().trim();

        const hrmsProfile =
          hrmsMapByExtId.get(uId) ||
          (code && hrmsMapByCode.get(code)) ||
          (email && hrmsMapByEmail.get(email)) ||
          null;

        return {
          userId: uId,
          employmentId: hrmsProfile?.employment_id || null,
          isHrmsLinked: Boolean(hrmsProfile?.employment_id),
          username: u.username,
          employeeCode: u.employee_code || u.employeeCode || hrmsProfile?.employee_code || u.username,
          name: `${u.first_name || ''} ${u.last_name || ''}`.trim() || hrmsProfile?.display_name || u.username,
          email: u.email || hrmsProfile?.email || '',
          role: u.role || 'User',
          department: u.department || hrmsProfile?.department || 'General',
          designation: u.designation || hrmsProfile?.designation || 'Staff',
          company: u.company || hrmsProfile?.company || 'Corporate',
        };
      });

      return res.json({ employees: employeesList, count: employeesList.length });
    } catch (err) {
      return handleHrmsError(res, err, 'Failed to fetch workforce directory');
    }
  });

  /**
   * POST /admin/mark-attendance
   * Direct 1-Click attendance override (Present, Absent, Half Day)
   */
  router.post('/admin/mark-attendance', async (req, res) => {
    try {
      if (!isAdminUser(req.user)) {
        return res.status(403).json({ message: 'Permission denied: Requires Admin or HOD role' });
      }

      const { user_id, work_date, status, punch_in, punch_out, reason } = req.body;
      if (!user_id || !work_date || !status) {
        return res.status(400).json({ message: 'user_id, work_date, and status are required' });
      }

      let targetUser = null;
      if (typeof options.findUserById === 'function') {
        targetUser = await options.findUserById(user_id);
      }
      if (!targetUser) {
        targetUser = { _id: user_id, id: user_id, username: 'employee' };
      }

      const normalizedStatus = status.toUpperCase();
      let correctionType = 'STATUS_OVERRIDE';
      let reqIn = punch_in || null;
      let reqOut = punch_out || null;

      if (normalizedStatus === 'PRESENT') {
        correctionType = 'MISSED_BOTH';
        if (!reqIn) reqIn = '09:30';
        if (!reqOut) reqOut = '18:30';
      } else if (normalizedStatus === 'HALF_DAY') {
        correctionType = 'MISSED_BOTH';
        if (!reqIn) reqIn = '09:30';
        if (!reqOut) reqOut = '13:30';
      }

      const requestReason = reason || `Marked ${normalizedStatus} by Admin (${req.user?.username || 'Admin'})`;

      try {
        const corrRes = await hrmsClient.requestCorrection({
          user: targetUser,
          workDate: work_date,
          correctionType,
          requestedPunchIn: reqIn,
          requestedPunchOut: reqOut,
          reason: requestReason,
        });

        if (corrRes && corrRes.id) {
          await hrmsClient.approveCorrection({
            user: req.user,
            correctionId: corrRes.id,
            comments: `Direct override to ${normalizedStatus} approved by Admin (${req.user.username})`,
          });
        }
      } catch (hrmsErr) {
        console.warn(`[Admin Mark Attendance] HRMS correction notice:`, hrmsErr.message);
      }

      if (typeof options.onAttendanceUpsert === 'function') {
        await options.onAttendanceUpsert({
          userId: user_id,
          workDate: work_date,
          status: normalizedStatus,
          punchIn: reqIn,
          punchOut: reqOut,
          markedBy: req.user?.username,
        });
      }

      return res.json({
        success: true,
        message: `Successfully marked ${normalizedStatus} for date ${work_date}!`,
        status: normalizedStatus,
      });
    } catch (err) {
      return handleHrmsError(res, err, 'Failed to mark attendance');
    }
  });

  /**
   * POST /sync-user/:userId
   * Force 1-click re-synchronization with HRMS
   */
  router.post('/sync-user/:userId', async (req, res) => {
    try {
      let targetUser = null;
      if (typeof options.findUserById === 'function') {
        targetUser = await options.findUserById(req.params.userId);
      }
      if (!targetUser) {
        targetUser = { _id: req.params.userId, id: req.params.userId };
      }

      const linked = await hrmsClient.linkUserToHrms(targetUser);
      return res.json({
        success: true,
        message: linked ? 'User linked successfully to HRMS employment' : 'Sync completed',
        employment: linked,
      });
    } catch (err) {
      return handleHrmsError(res, err, 'Failed to synchronize user');
    }
  });

  /**
   * POST /onboard
   * Auto-Sync Onboarding: Push new or existing employee to HRMS with full employment creation.
   */
  router.post('/onboard', async (req, res) => {
    try {
      const targetUser = req.body.user || req.body;
      const externalId = String(targetUser._id || targetUser.id || targetUser.userId || targetUser.external_id || '');
      if (!externalId) {
        return res.status(400).json({ error: 'User ID or external_id is required for onboarding sync' });
      }

      const formatted = hrmsClient.formatUserForHrms(targetUser);
      const result = await hrmsClient.upsertEmployee(externalId, formatted, {
        dryRun: Boolean(req.body.dryRun),
      });

      return res.status(200).json({
        success: true,
        message: 'Employee onboarded and auto-synced to HRMS successfully',
        externalId,
        hrmsResult: result,
      });
    } catch (err) {
      return handleHrmsError(res, err, 'Failed to onboard and sync employee with HRMS');
    }
  });

  /**
   * GET /health
   * Connectivity check
   */
  router.get('/health', async (req, res) => {
    try {
      const emps = await hrmsClient.getIntegrationEmployees();
      return res.json({
        status: 'UP',
        integration: 'CONNECTED',
        totalEmployees: emps.length,
        timestamp: new Date().toISOString(),
      });
    } catch (err) {
      return res.status(503).json({
        status: 'DOWN',
        integration: 'OFFLINE',
        error: err.message,
      });
    }
  });

  return router;
}

export default createAttendanceV2Router;
