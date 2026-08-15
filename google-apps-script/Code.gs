/**
 * ============================================================================
 * Bandhan.ai — "First Access" waitlist backend
 * Google Apps Script  →  Google Sheets
 * ============================================================================
 *
 * What it does
 *   • Accepts submissions from the landing page (POST JSON, POST form, or GET).
 *   • Creates the spreadsheet tab and the header row automatically on first run.
 *   • Repairs / extends headers if the schema changes later, without losing data.
 *   • De-duplicates by email: a repeat submit updates the existing row and
 *     increments a counter instead of creating a second lead.
 *   • Captures the full "first access" context: contact details, the message,
 *     device, browser, referrer, UTM tags, page and locale.
 *   • Never throws to the caller. Every failure is logged to an "Error Log" tab
 *     and returned as a structured JSON error.
 *
 * Public entry points:  doGet(e), doPost(e), setup(), onOpen()
 * Test entry point:     runAllTests()   (see Tests.gs)
 *
 * Deployment: see SETUP.md
 * ============================================================================
 */

/* -------------------------------------------------------------------------
 * 1. CONFIGURATION — the only part you normally edit
 * ---------------------------------------------------------------------- */

var CONFIG = {
  /**
   * Leave '' when this script is bound to the spreadsheet (Extensions > Apps
   * Script from inside the Sheet). Set the spreadsheet ID when it is a
   * standalone script. The ID is the long part of the sheet URL:
   * docs.google.com/spreadsheets/d/<THIS_PART>/edit
   */
  SPREADSHEET_ID: '',

  /** Tab that stores leads. Created automatically if missing. */
  SHEET_NAME: 'First Access',

  /** Tab that stores server-side errors. Created only when something fails. */
  ERROR_SHEET_NAME: 'Error Log',

  /** true = a repeat email updates the existing row instead of adding one. */
  DEDUPE_BY_EMAIL: true,

  /** Set an address to get an email per new signup. '' = no notifications. */
  NOTIFY_EMAIL: '',

  /**
   * Optional shared secret. When set, the request must include the same value
   * as "token". Keep '' for a public landing page (the token would be visible
   * in the page source anyway).
   */
  SHARED_SECRET: '',

  /** Allow submissions over GET. Needed for the no-CORS browser fallback. */
  ALLOW_GET_SUBMIT: true,

  /** How long to wait for the write lock, in milliseconds. */
  LOCK_TIMEOUT_MS: 25000,

  /** Long free-text fields are trimmed to this many characters. */
  MAX_TEXT_LENGTH: 4000,

  /** Used for the spreadsheet timezone on first creation. */
  TIME_ZONE: 'Asia/Kolkata',

  /** Values offered in the Status dropdown. */
  STATUS_VALUES: ['New', 'Invited', 'Joined', 'Bounced', 'Unsubscribed']
};

/**
 * The sheet schema. Order here = column order in a freshly created sheet.
 * `key` is the field on the internal record, `header` is the text written to
 * row 1. Rows are written by header lookup, so you can safely add a new entry
 * to the end of this list later — existing data stays put.
 */
var SCHEMA = [
  { key: 'timestamp',   header: 'Timestamp',        width: 155, format: 'yyyy-mm-dd hh:mm:ss' },
  { key: 'entryId',     header: 'Entry ID',         width: 110 },
  { key: 'name',        header: 'Name',             width: 180 },
  { key: 'email',       header: 'Email',            width: 230 },
  { key: 'phone',       header: 'Phone',            width: 150, format: '@' },
  { key: 'segment',     header: 'Sending To',       width: 165 },
  { key: 'message',     header: 'Message',          width: 320, wrap: true },
  { key: 'feedback',    header: 'Feedback',         width: 280, wrap: true },
  { key: 'handle',      header: 'Reserved Handle',  width: 170 },
  { key: 'status',      header: 'Status',           width: 110 },
  { key: 'submissions', header: 'Submissions',      width: 95,  format: '0' },
  { key: 'lastUpdated', header: 'Last Updated',     width: 155, format: 'yyyy-mm-dd hh:mm:ss' },
  { key: 'sourceUrl',   header: 'Page',             width: 220 },
  { key: 'referrer',    header: 'Referrer',         width: 200 },
  { key: 'utmSource',   header: 'UTM Source',       width: 120 },
  { key: 'utmMedium',   header: 'UTM Medium',       width: 120 },
  { key: 'utmCampaign', header: 'UTM Campaign',     width: 140 },
  { key: 'device',      header: 'Device',           width: 100 },
  { key: 'browser',     header: 'Browser',          width: 110 },
  { key: 'os',          header: 'OS',               width: 110 },
  { key: 'language',    header: 'Language',         width: 100 },
  { key: 'clientTz',    header: 'Client Timezone',  width: 150 },
  { key: 'screen',      header: 'Screen',           width: 110 },
  { key: 'userAgent',   header: 'User Agent',       width: 300 }
];

var ERROR_SCHEMA = [
  { key: 'timestamp', header: 'Timestamp', width: 165, format: 'yyyy-mm-dd hh:mm:ss' },
  { key: 'where',     header: 'Where',     width: 160 },
  { key: 'message',   header: 'Message',   width: 380, wrap: true },
  { key: 'stack',     header: 'Stack',     width: 420, wrap: true },
  { key: 'payload',   header: 'Payload',   width: 420, wrap: true }
];

/* -------------------------------------------------------------------------
 * 2. WEB ENTRY POINTS
 * ---------------------------------------------------------------------- */

/**
 * GET. Two jobs:
 *   • no parameters (or action=ping)  → health check you can open in a browser
 *   • action=submit + fields          → the no-CORS fallback used by the page
 * Supports JSONP via &callback=fn.
 */
function doGet(e) {
  var req = normalizeEvent_(e);
  try {
    var action = String(req.data.action || 'ping').toLowerCase();

    if (action === 'submit') {
      if (!CONFIG.ALLOW_GET_SUBMIT) {
        return reply_(req, errorPayload_('METHOD_NOT_ALLOWED', 'Use POST to submit.'));
      }
      return reply_(req, handleSubmit_(req));
    }
    return reply_(req, healthPayload_());
  } catch (err) {
    logError_('doGet', err, req.raw);
    return reply_(req, errorPayload_('SERVER_ERROR', 'Could not process the request.'));
  }
}

/** POST. Accepts JSON body, text/plain JSON body, or form-encoded fields. */
function doPost(e) {
  var req = normalizeEvent_(e);
  try {
    var action = String(req.data.action || 'submit').toLowerCase();
    if (action === 'ping') return reply_(req, healthPayload_());
    return reply_(req, handleSubmit_(req));
  } catch (err) {
    logError_('doPost', err, req.raw);
    return reply_(req, errorPayload_('SERVER_ERROR', 'Could not process the request.'));
  }
}

/** Adds a "Bandhan.ai" menu inside the spreadsheet. */
function onOpen() {
  try {
    SpreadsheetApp.getUi()
      .createMenu('Bandhan.ai')
      .addItem('Set up / repair sheet', 'setup')
      .addItem('Run self-test', 'runAllTests')
      .addSeparator()
      .addItem('Show deployment status', 'showStatus')
      .addToUi();
  } catch (err) {
    // No UI context (triggered from the script editor) — nothing to do.
  }
}

/**
 * Run once from the editor, or from the Bandhan.ai menu. Creates the tab,
 * writes and formats the headers, and confirms the script can write.
 */
function setup() {
  var ss = getSpreadsheet_();
  var sheet = ensureSheet_(ss, CONFIG.SHEET_NAME, SCHEMA);
  var summary =
    'Spreadsheet : ' + ss.getName() + '\n' +
    'URL         : ' + ss.getUrl() + '\n' +
    'Tab         : ' + sheet.getName() + '\n' +
    'Columns     : ' + SCHEMA.length + '\n' +
    'Rows so far : ' + Math.max(0, sheet.getLastRow() - 1);
  Logger.log(summary);
  try {
    SpreadsheetApp.getUi().alert('Setup complete\n\n' + summary);
  } catch (err) {
    // Running headless.
  }
  return summary;
}

/** Menu helper: prints where data lands and how many rows exist. */
function showStatus() {
  var payload = healthPayload_();
  var text = JSON.stringify(payload, null, 2);
  Logger.log(text);
  try {
    SpreadsheetApp.getUi().alert('Status', text, SpreadsheetApp.getUi().ButtonSet.OK);
  } catch (err) {
    // Running headless.
  }
  return payload;
}

/* -------------------------------------------------------------------------
 * 3. REQUEST HANDLING
 * ---------------------------------------------------------------------- */

/**
 * Flattens the many shapes an Apps Script event can take into
 * { data: {...}, raw: '...' }. Never throws.
 */
function normalizeEvent_(e) {
  var data = {};
  var raw = '';

  if (e && e.parameter) {
    for (var k in e.parameter) {
      if (Object.prototype.hasOwnProperty.call(e.parameter, k)) data[k] = e.parameter[k];
    }
  }

  if (e && e.postData && e.postData.contents) {
    raw = String(e.postData.contents);
    var trimmed = raw.replace(/^﻿/, '').trim();
    if (trimmed.charAt(0) === '{' || trimmed.charAt(0) === '[') {
      try {
        var parsed = JSON.parse(trimmed);
        if (parsed && typeof parsed === 'object' && !(parsed instanceof Array)) {
          for (var j in parsed) {
            if (Object.prototype.hasOwnProperty.call(parsed, j)) data[j] = parsed[j];
          }
        }
      } catch (err) {
        // Body was not valid JSON; the form parameters above still apply.
      }
    }
  }

  return { data: data, raw: raw || JSON.stringify(data), callback: data.callback || '' };
}

/**
 * Validates, writes and returns the response payload for one submission.
 * Wrapped in a script lock so simultaneous visitors cannot claim the same row.
 */
function handleSubmit_(req) {
  var data = req.data;

  if (CONFIG.SHARED_SECRET && String(data.token || '') !== CONFIG.SHARED_SECRET) {
    return errorPayload_('UNAUTHORIZED', 'Invalid token.');
  }

  var record = buildRecord_(data);
  var problems = validate_(record);
  if (problems.length) {
    return errorPayload_('VALIDATION_FAILED', problems[0], { fields: problems });
  }

  var lock = LockService.getScriptLock();
  var locked = false;
  try {
    locked = lock.tryLock(CONFIG.LOCK_TIMEOUT_MS);
    if (!locked) return errorPayload_('BUSY', 'The list is busy. Please try again in a moment.');

    var ss = getSpreadsheet_();
    var sheet = ensureSheet_(ss, CONFIG.SHEET_NAME, SCHEMA);
    var result = upsert_(sheet, record);

    SpreadsheetApp.flush();
    notify_(record, result);

    return {
      ok: true,
      status: result.status,          // 'created' | 'updated'
      entryId: result.entryId,
      handle: record.handle,
      row: result.row,
      message: result.status === 'created'
        ? "You're on the first-access list."
        : "You were already on the list — we've refreshed your details."
    };
  } catch (err) {
    logError_('handleSubmit_', err, req.raw);
    return errorPayload_('WRITE_FAILED', 'We could not save your details. Please try again.');
  } finally {
    if (locked) {
      try { lock.releaseLock(); } catch (err2) { /* lock already gone */ }
    }
  }
}

/* -------------------------------------------------------------------------
 * 4. RECORD BUILDING, CLEANING AND VALIDATION
 * ---------------------------------------------------------------------- */

/** Maps an arbitrary request object onto the internal record shape. */
function buildRecord_(data) {
  var now = new Date();
  var name = clean_(pick_(data, ['name', 'fullName', 'full_name']), 120);
  var email = clean_(pick_(data, ['email', 'emailAddress', 'email_address']), 254).toLowerCase();
  var phone = normalizePhone_(pick_(data, ['phone', 'mobile', 'phoneNumber', 'phone_number']));
  var ua = clean_(pick_(data, ['userAgent', 'ua', 'user_agent']), 500);

  return {
    timestamp: now,
    entryId: makeEntryId_(now),
    name: name,
    email: email,
    phone: phone,
    segment: clean_(pick_(data, ['segment', 'sendingTo', 'audience']), 120) || 'Not specified',
    message: clean_(pick_(data, ['message', 'note']), CONFIG.MAX_TEXT_LENGTH),
    feedback: clean_(pick_(data, ['feedback', 'suggestion']), CONFIG.MAX_TEXT_LENGTH),
    handle: clean_(pick_(data, ['handle']), 80) || makeHandle_(name, email, now),
    status: 'New',
    submissions: 1,
    lastUpdated: now,
    sourceUrl: clean_(pick_(data, ['sourceUrl', 'page', 'url']), 500),
    referrer: clean_(pick_(data, ['referrer', 'referer']), 500),
    utmSource: clean_(pick_(data, ['utmSource', 'utm_source']), 120),
    utmMedium: clean_(pick_(data, ['utmMedium', 'utm_medium']), 120),
    utmCampaign: clean_(pick_(data, ['utmCampaign', 'utm_campaign']), 120),
    device: deviceFromUa_(ua),
    browser: browserFromUa_(ua),
    os: osFromUa_(ua),
    language: clean_(pick_(data, ['language', 'lang']), 40),
    clientTz: clean_(pick_(data, ['clientTz', 'timezone', 'tz']), 80),
    screen: clean_(pick_(data, ['screen', 'viewport']), 40),
    userAgent: ua
  };
}

/** Returns an array of human-readable problems; empty means valid. */
function validate_(record) {
  var problems = [];
  if (!record.name) problems.push('Please add your name so we know who to greet.');
  if (!isEmail_(record.email)) problems.push("That email doesn't look right. Check it once?");
  var digits = record.phone.replace(/\D/g, '');
  if (digits.length < 10 || digits.length > 15) {
    problems.push('Please add a phone number we can reach you on.');
  }
  return problems;
}

function isEmail_(value) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(String(value || ''));
}

/** First non-empty value among several possible field names. */
function pick_(data, keys) {
  for (var i = 0; i < keys.length; i++) {
    var v = data[keys[i]];
    if (v !== undefined && v !== null && String(v).trim() !== '') return v;
  }
  return '';
}

/**
 * Trims, collapses control characters, caps length, and neutralises formula
 * injection (a value starting with = + - @ would otherwise execute in Sheets).
 */
function clean_(value, maxLength) {
  if (value === undefined || value === null) return '';
  var text = stripControlChars_(String(value)).trim();
  if (maxLength && text.length > maxLength) text = text.substring(0, maxLength);
  if (/^[=+\-@]/.test(text)) text = "'" + text;
  return text;
}

/** Drops non-printable characters but keeps tab, newline and return. */
function stripControlChars_(text) {
  var out = [];
  for (var i = 0; i < text.length; i++) {
    var code = text.charCodeAt(i);
    if (code === 9 || code === 10 || code === 13) { out.push(text.charAt(i)); continue; }
    if (code < 32 || code === 127) continue;
    out.push(text.charAt(i));
  }
  return out.join('');
}

/** Keeps digits and a single leading +, so "+91 98765 43210" stays readable. */
function normalizePhone_(value) {
  var text = String(value === undefined || value === null ? '' : value).trim();
  if (!text) return '';
  var plus = text.charAt(0) === '+';
  var digits = text.replace(/\D/g, '');
  if (digits.length > 15) digits = digits.substring(0, 15);
  return digits ? (plus ? '+' + digits : digits) : '';
}

function makeEntryId_(now) {
  var stamp = Utilities.formatDate(now, CONFIG.TIME_ZONE, 'yyMMdd');
  var uuid = Utilities.getUuid().replace(/-/g, '').substring(0, 6).toUpperCase();
  return 'BA-' + stamp + '-' + uuid;
}

/** Mirrors the handle shown on the landing page: "ananya-sharma-2026". */
function makeHandle_(name, email, now) {
  var base = String(name || String(email || '').split('@')[0] || 'rakhi')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return (base || 'rakhi') + '-' + now.getFullYear();
}

function deviceFromUa_(ua) {
  if (!ua) return '';
  if (/iPad|Tablet|PlayBook|Silk/i.test(ua)) return 'Tablet';
  if (/Mobi|Android|iPhone|iPod|Windows Phone/i.test(ua)) return 'Mobile';
  return 'Desktop';
}

function browserFromUa_(ua) {
  if (!ua) return '';
  if (/Edg\//i.test(ua)) return 'Edge';
  if (/OPR\/|Opera/i.test(ua)) return 'Opera';
  if (/SamsungBrowser/i.test(ua)) return 'Samsung Internet';
  if (/Chrome\//i.test(ua)) return 'Chrome';
  if (/Firefox\//i.test(ua)) return 'Firefox';
  if (/Safari\//i.test(ua)) return 'Safari';
  return 'Other';
}

function osFromUa_(ua) {
  if (!ua) return '';
  if (/Windows NT/i.test(ua)) return 'Windows';
  if (/Android/i.test(ua)) return 'Android';
  if (/iPhone|iPad|iPod/i.test(ua)) return 'iOS';
  if (/Mac OS X/i.test(ua)) return 'macOS';
  if (/Linux/i.test(ua)) return 'Linux';
  return 'Other';
}

/* -------------------------------------------------------------------------
 * 5. SPREADSHEET ACCESS
 * ---------------------------------------------------------------------- */

/** Bound spreadsheet when available, otherwise CONFIG.SPREADSHEET_ID. */
function getSpreadsheet_() {
  if (CONFIG.SPREADSHEET_ID) return SpreadsheetApp.openById(CONFIG.SPREADSHEET_ID);
  var active = SpreadsheetApp.getActiveSpreadsheet();
  if (active) return active;
  throw new Error(
    'No spreadsheet found. Either bind this script to a Sheet ' +
    '(Extensions > Apps Script) or set CONFIG.SPREADSHEET_ID.'
  );
}

/**
 * Returns the tab, creating it if needed, and guarantees every header in the
 * schema exists. Missing headers are appended to the right so existing columns
 * keep their data.
 */
function ensureSheet_(ss, sheetName, schema) {
  var sheet = ss.getSheetByName(sheetName);
  var created = false;

  if (!sheet) {
    sheet = ss.insertSheet(sheetName);
    created = true;
  }

  var lastCol = sheet.getLastColumn();
  var existing = lastCol > 0 ? sheet.getRange(1, 1, 1, lastCol).getValues()[0] : [];
  var headerRow = [];
  for (var i = 0; i < existing.length; i++) headerRow.push(String(existing[i] || '').trim());

  var hasHeaders = false;
  for (var h = 0; h < headerRow.length; h++) {
    if (headerRow[h] !== '') { hasHeaders = true; break; }
  }

  if (!hasHeaders) {
    headerRow = schema.map(function (col) { return col.header; });
    writeHeaderRow_(sheet, headerRow);
    formatSheet_(sheet, schema, headerRow);
    return sheet;
  }

  // Append any header the schema knows about but the sheet does not.
  var missing = schema.filter(function (col) { return headerRow.indexOf(col.header) === -1; });
  if (missing.length) {
    missing.forEach(function (col) { headerRow.push(col.header); });
    writeHeaderRow_(sheet, headerRow);
  }

  if (created || missing.length) formatSheet_(sheet, schema, headerRow);
  return sheet;
}

function writeHeaderRow_(sheet, headerRow) {
  var maxCols = sheet.getMaxColumns();
  if (maxCols < headerRow.length) sheet.insertColumnsAfter(maxCols, headerRow.length - maxCols);
  sheet.getRange(1, 1, 1, headerRow.length).setValues([headerRow]);
}

/** Cosmetics + column formats. Safe to run repeatedly. */
function formatSheet_(sheet, schema, headerRow) {
  try {
    var width = headerRow.length;
    var header = sheet.getRange(1, 1, 1, width);
    header
      .setBackground('#2C0E15')
      .setFontColor('#F7EAE6')
      .setFontWeight('bold')
      .setFontSize(11)
      .setVerticalAlignment('middle')
      .setHorizontalAlignment('left')
      .setWrap(false);
    sheet.setFrozenRows(1);
    sheet.setRowHeight(1, 34);

    var index = headerIndex_(headerRow);

    schema.forEach(function (col) {
      var pos = index[col.header];
      if (!pos) return;
      if (col.width) sheet.setColumnWidth(pos, col.width);
      var maxRows = sheet.getMaxRows();
      if (maxRows > 1) {
        var body = sheet.getRange(2, pos, maxRows - 1, 1);
        if (col.format) body.setNumberFormat(col.format);
        if (col.wrap) body.setWrap(true);
        if (col.key === 'status' && CONFIG.STATUS_VALUES && CONFIG.STATUS_VALUES.length) {
          var rule = SpreadsheetApp.newDataValidation()
            .requireValueInList(CONFIG.STATUS_VALUES, true)
            .setAllowInvalid(true)
            .build();
          body.setDataValidation(rule);
        }
      }
    });

    if (!sheet.getFilter() && sheet.getLastColumn() > 0) {
      sheet.getRange(1, 1, sheet.getMaxRows(), headerRow.length).createFilter();
    }
  } catch (err) {
    // Formatting is cosmetic — never let it block a signup.
    logError_('formatSheet_', err, sheet ? sheet.getName() : '');
  }
}

/** { 'Header text': 1-based column } */
function headerIndex_(headerRow) {
  var map = {};
  for (var i = 0; i < headerRow.length; i++) {
    var key = String(headerRow[i] || '').trim();
    if (key && !map[key]) map[key] = i + 1;
  }
  return map;
}

function readHeaderRow_(sheet) {
  var lastCol = sheet.getLastColumn();
  if (lastCol < 1) return [];
  var values = sheet.getRange(1, 1, 1, lastCol).getValues()[0];
  return values.map(function (v) { return String(v || '').trim(); });
}

/* -------------------------------------------------------------------------
 * 6. WRITING
 * ---------------------------------------------------------------------- */

/** Inserts a new lead, or refreshes the existing one when the email repeats. */
function upsert_(sheet, record) {
  var headerRow = readHeaderRow_(sheet);
  var index = headerIndex_(headerRow);
  var existingRow = CONFIG.DEDUPE_BY_EMAIL ? findRowByEmail_(sheet, index, record.email) : 0;

  if (existingRow > 0) {
    var current = sheet.getRange(existingRow, 1, 1, headerRow.length).getValues()[0];
    var previousId = index['Entry ID'] ? String(current[index['Entry ID'] - 1] || '') : '';
    var previousCount = index['Submissions'] ? Number(current[index['Submissions'] - 1]) : 0;
    if (!previousCount || isNaN(previousCount)) previousCount = 1;

    var updated = {
      name: record.name,
      phone: record.phone,
      segment: record.segment,
      message: record.message,
      feedback: record.feedback,
      handle: record.handle,
      lastUpdated: record.lastUpdated,
      submissions: previousCount + 1,
      sourceUrl: record.sourceUrl,
      referrer: record.referrer,
      utmSource: record.utmSource,
      utmMedium: record.utmMedium,
      utmCampaign: record.utmCampaign,
      device: record.device,
      browser: record.browser,
      os: record.os,
      language: record.language,
      clientTz: record.clientTz,
      screen: record.screen,
      userAgent: record.userAgent
    };

    // Keep the original Timestamp, Entry ID and Status untouched.
    SCHEMA.forEach(function (col) {
      var pos = index[col.header];
      if (!pos) return;
      if (!Object.prototype.hasOwnProperty.call(updated, col.key)) return;
      var value = updated[col.key];
      if (value === '' && String(current[pos - 1] || '') !== '') return; // don't blank existing data
      current[pos - 1] = value;
    });

    sheet.getRange(existingRow, 1, 1, headerRow.length).setValues([current]);
    return { status: 'updated', row: existingRow, entryId: previousId || record.entryId };
  }

  var row = new Array(headerRow.length);
  for (var i = 0; i < row.length; i++) row[i] = '';
  SCHEMA.forEach(function (col) {
    var pos = index[col.header];
    if (pos) row[pos - 1] = record[col.key] === undefined ? '' : record[col.key];
  });

  var target = sheet.getLastRow() + 1;
  if (target < 2) target = 2;
  var maxRows = sheet.getMaxRows();
  if (target > maxRows) sheet.insertRowsAfter(maxRows, target - maxRows);
  sheet.getRange(target, 1, 1, row.length).setValues([row]);

  return { status: 'created', row: target, entryId: record.entryId };
}

/** 1-based row of the matching email, or 0. */
function findRowByEmail_(sheet, index, email) {
  var col = index['Email'];
  var lastRow = sheet.getLastRow();
  if (!col || lastRow < 2 || !email) return 0;
  var values = sheet.getRange(2, col, lastRow - 1, 1).getValues();
  var needle = String(email).trim().toLowerCase();
  for (var i = 0; i < values.length; i++) {
    if (String(values[i][0] || '').trim().toLowerCase() === needle) return i + 2;
  }
  return 0;
}

/* -------------------------------------------------------------------------
 * 7. RESPONSES, NOTIFICATIONS, ERROR LOG
 * ---------------------------------------------------------------------- */

/** JSON (or JSONP when ?callback= is present). */
function reply_(req, payload) {
  var json = JSON.stringify(payload);
  var callback = req && req.callback ? String(req.callback) : '';
  if (callback && /^[A-Za-z_$][A-Za-z0-9_$.]*$/.test(callback)) {
    return ContentService
      .createTextOutput(callback + '(' + json + ');')
      .setMimeType(ContentService.MimeType.JAVASCRIPT);
  }
  return ContentService
    .createTextOutput(json)
    .setMimeType(ContentService.MimeType.JSON);
}

function errorPayload_(code, message, extra) {
  var payload = { ok: false, error: { code: code, message: message } };
  if (extra) {
    for (var k in extra) {
      if (Object.prototype.hasOwnProperty.call(extra, k)) payload.error[k] = extra[k];
    }
  }
  return payload;
}

function healthPayload_() {
  var info = { ok: true, service: 'bandhan-first-access', version: '1.0.0', time: new Date().toISOString() };
  try {
    var ss = getSpreadsheet_();
    var sheet = ss.getSheetByName(CONFIG.SHEET_NAME);
    info.spreadsheet = ss.getName();
    info.sheet = CONFIG.SHEET_NAME;
    info.ready = !!sheet;
    info.entries = sheet ? Math.max(0, sheet.getLastRow() - 1) : 0;
  } catch (err) {
    info.ready = false;
    info.note = 'Spreadsheet not reachable yet. Run setup() once.';
  }
  return info;
}

/** Optional signup email. Failures here must never break the response. */
function notify_(record, result) {
  if (!CONFIG.NOTIFY_EMAIL || result.status !== 'created') return;
  try {
    MailApp.sendEmail({
      to: CONFIG.NOTIFY_EMAIL,
      subject: 'First access signup — ' + record.name,
      body:
        'Name     : ' + record.name + '\n' +
        'Email    : ' + record.email + '\n' +
        'Phone    : ' + record.phone + '\n' +
        'Sending to: ' + record.segment + '\n' +
        'Handle   : ' + record.handle + '\n\n' +
        'Message  : ' + (record.message || '—') + '\n' +
        'Feedback : ' + (record.feedback || '—') + '\n\n' +
        'Row ' + result.row + ' · ' + result.entryId
    });
  } catch (err) {
    logError_('notify_', err, record.email);
  }
}

/**
 * Appends to the Error Log tab. Silent if even that fails.
 * IN_LOG_ERROR guards the logError_ -> ensureSheet_ -> formatSheet_ -> logError_
 * path so a formatting failure can never recurse.
 */
var IN_LOG_ERROR = false;

function logError_(where, err, payload) {
  try {
    Logger.log(where + ': ' + (err && err.message ? err.message : err));
  } catch (ignored) { /* Logger unavailable */ }

  if (IN_LOG_ERROR) return;
  IN_LOG_ERROR = true;
  try {
    var ss = getSpreadsheet_();
    var sheet = ensureSheet_(ss, CONFIG.ERROR_SHEET_NAME, ERROR_SCHEMA);
    var headerRow = readHeaderRow_(sheet);
    var index = headerIndex_(headerRow);
    var record = {
      timestamp: new Date(),
      where: String(where || ''),
      message: String(err && err.message ? err.message : err).substring(0, 1000),
      stack: String(err && err.stack ? err.stack : '').substring(0, 2000),
      payload: String(payload === undefined ? '' : payload).substring(0, 2000)
    };
    var row = new Array(headerRow.length);
    for (var i = 0; i < row.length; i++) row[i] = '';
    ERROR_SCHEMA.forEach(function (col) {
      var pos = index[col.header];
      if (pos) row[pos - 1] = record[col.key];
    });
    var target = Math.max(2, sheet.getLastRow() + 1);
    sheet.getRange(target, 1, 1, row.length).setValues([row]);
  } catch (ignored) {
    // Logging must never throw into the request path.
  } finally {
    IN_LOG_ERROR = false;
  }
}
