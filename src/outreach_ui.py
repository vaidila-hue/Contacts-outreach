"""Local Flask UI for CRM outreach review and Gmail actions."""

from __future__ import annotations

import argparse

from flask import Flask, redirect, render_template_string, request, url_for

from src.gmail_client import build_gmail_service, verify_gmail_account
from src.harvest_config_store import HarvestConfigSettings, load_harvest_config, save_harvest_config as persist_harvest_config
from src.harvest_runner import run_find_more_contacts
from src.outreach_cli import run_outreach_send_ready
from src.outreach_crm import FILTER_OPTIONS, compute_dashboard, format_sent_date_display, row_matches_filter
from src.outreach_store import (
    delete_outreach_row,
    read_outreach_rows,
    row_message_templates,
    save_default_message_for_outreach,
    save_row_message as persist_row_message,
    update_outreach_rows,
)
from src.outreach_template import load_default_message
from src.outreach_test import (
    DEFAULT_TEST_GREETING,
    TEST_RECIPIENT_EMAIL,
    TEST_RECIPIENT_NAME,
    create_test_draft,
    load_test_history,
    render_test_outreach,
    send_test_email,
)
from src.outreach_launch import CRM_URL, check_port_available, schedule_browser_open
from src.paths import OUTREACH_PORT, REPLY_STATUS_VALUES

US_STATE_CODES = (
    "AL,AK,AZ,AR,CA,CO,CT,DE,FL,GA,HI,ID,IL,IN,IA,KS,KY,LA,ME,MD,MA,MI,MN,MS,MO,"
    "MT,NE,NV,NH,NJ,NM,NY,NC,ND,OH,OK,OR,PA,RI,SC,SD,TN,TX,UT,VT,VA,WA,WV,WI,WY,DC"
).split(",")

PAGE_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Planzookie Outreach CRM</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 16px; }
    h1 { margin-bottom: 8px; }
    .dashboard { display: flex; flex-wrap: wrap; gap: 16px; margin: 0 0 12px; padding: 10px; background: #f7f7f7; border: 1px solid #ddd; }
    .metric { min-width: 100px; }
    .metric strong { display: block; font-size: 20px; }
    .filters { margin: 8px 0; display: flex; flex-wrap: wrap; gap: 6px; }
    .filters a { padding: 4px 10px; border: 1px solid #888; text-decoration: none; color: #111; font-size: 13px; }
    .filters a.active { background: #333; color: #fff; }
    table { border-collapse: collapse; width: 100%; font-size: 12px; }
    th, td { border: 1px solid #ccc; padding: 4px 6px; vertical-align: top; }
    th { background: #f3f3f3; position: sticky; top: 0; z-index: 1; }
    tbody tr.row-alt { background: #f7f7f7; }
    .actions { margin: 12px 0; display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
    .actions button, .actions a.btn { padding: 8px 12px; cursor: pointer; text-decoration: none; color: #111; border: 1px solid #888; background: #fafafa; display: inline-block; font-size: 13px; }
    .status-sent { color: #0a0; font-weight: bold; }
    .status-failed { color: #a00; font-weight: bold; }
    input[type=text], input[type=datetime-local], select, textarea { width: 100%; min-width: 70px; box-sizing: border-box; font-size: 12px; }
    textarea { min-height: 48px; }
    .msg { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; padding: 8px 10px; background: #eef6ff; border: 1px solid #99c; margin-bottom: 12px; }
    .msg span { flex: 1; white-space: pre-line; }
    .msg.hidden { display: none; }
    .msg.warn { background: #fff8e6; border-color: #cc9; }
    .msg-dismiss { background: none; border: none; font-size: 18px; line-height: 1; cursor: pointer; color: #444; padding: 0 4px; }
    .modal-backdrop { display: none; position: fixed; inset: 0; background: rgba(0,0,0,.4); z-index: 10; }
    .modal-backdrop.open { display: flex; align-items: center; justify-content: center; }
    .modal { background: #fff; padding: 16px; border: 1px solid #888; max-width: 520px; width: 90%; max-height: 90vh; overflow: auto; }
    .modal label { display: block; font-weight: bold; margin-top: 8px; }
    .modal select[multiple] { height: 140px; }
    .modal .row { display: flex; gap: 12px; }
    .modal .row > div { flex: 1; }
    .modal textarea.body-field { min-height: 220px; }
    .link-btn { background: none; border: none; color: #06c; cursor: pointer; text-decoration: underline; padding: 0; font-size: 12px; }
    .row-menu { position: relative; display: inline-block; }
    .menu-trigger { background: none; border: none; cursor: pointer; font-size: 18px; line-height: 1; padding: 2px 8px; color: #444; }
    .menu-dropdown { display: none; position: absolute; right: 0; top: 100%; background: #fff; border: 1px solid #ccc; box-shadow: 0 2px 6px rgba(0,0,0,.12); z-index: 5; min-width: 110px; }
    .row-menu.open .menu-dropdown { display: block; }
    .menu-dropdown button { display: block; width: 100%; text-align: left; padding: 7px 12px; border: none; background: none; cursor: pointer; font-size: 12px; }
    .menu-dropdown button:hover { background: #f0f0f0; }
    .menu-delete { color: #a00; }
  </style>
  <script>
    function closeRowMenus() {
      document.querySelectorAll('.row-menu.open').forEach(function(el) { el.classList.remove('open'); });
    }
    function toggleRowMenu(idx, event) {
      event.stopPropagation();
      var menu = document.getElementById('row-menu-' + idx);
      var wasOpen = menu.classList.contains('open');
      closeRowMenus();
      if (!wasOpen) menu.classList.add('open');
    }
    document.addEventListener('click', closeRowMenus);
    function confirmDeleteRow(idx) {
      closeRowMenus();
      if (confirm('Remove this contact from the CRM? This cannot be undone.')) {
        document.getElementById('delete-form-' + idx).submit();
      }
    }
    function initFlashMessage() {
      var flash = document.getElementById('flash-msg');
      if (!flash) return;
      var hide = function() { flash.classList.add('hidden'); };
      var btn = flash.querySelector('.msg-dismiss');
      if (btn) btn.addEventListener('click', hide);
      setTimeout(hide, 5000);
    }
    document.addEventListener('DOMContentLoaded', initFlashMessage);
    function openDefaultMessageModal() {
      document.getElementById('default-message-modal').classList.add('open');
    }
    function openRowMessageModal(idx) {
      document.getElementById('row-msg-orig-email').value = document.getElementById('orig-email-' + idx).value;
      document.getElementById('row-msg-orig-state').value = document.getElementById('orig-state-' + idx).value;
      document.getElementById('row-msg-orig-jurisdiction').value = document.getElementById('orig-jurisdiction-' + idx).value;
      document.getElementById('row-msg-subject').value = document.getElementById('row-subject-' + idx).value;
      document.getElementById('row-msg-body').value = document.getElementById('row-body-' + idx).value;
      document.getElementById('row-message-modal').classList.add('open');
    }
    function openDetailsModal(idx) {
      closeRowMenus();
      ['jurisdiction_type','population','jurisdiction_url','email_source_url','first_reply_at',
       'follow_up_at','meeting_requested','meeting_scheduled_for','meeting_completed','follow_up_needed'].forEach(function(f) {
        var el = document.getElementById(f + '-' + idx);
        var target = document.getElementById('detail-' + f);
        if (el && target) {
          if (el.type === 'checkbox') target.checked = el.checked;
          else target.value = el.value;
        }
      });
      document.getElementById('detail-row-idx').value = idx;
      document.getElementById('details-modal').classList.add('open');
    }
    function saveDetailsToRow() {
      var idx = document.getElementById('detail-row-idx').value;
      ['jurisdiction_type','population','jurisdiction_url','email_source_url','first_reply_at',
       'follow_up_at','meeting_scheduled_for'].forEach(function(f) {
        document.getElementById(f + '-' + idx).value = document.getElementById('detail-' + f).value;
      });
      document.getElementById('meeting_requested-' + idx).checked = document.getElementById('detail-meeting_requested').checked;
      document.getElementById('meeting_completed-' + idx).checked = document.getElementById('detail-meeting_completed').checked;
      document.getElementById('follow_up_needed-' + idx).checked = document.getElementById('detail-follow_up_needed').checked;
      document.getElementById('follow_up_at-' + idx).value = document.getElementById('detail-follow_up_at').value;
      document.getElementById('details-modal').classList.remove('open');
    }
  </script>
</head>
<body>
  <h1>Planzookie Outreach CRM</h1>
  {% if message %}
  <div class="msg" id="flash-msg" role="status">
    <span>{{ message }}</span>
    <button type="button" class="msg-dismiss" aria-label="Dismiss">&times;</button>
  </div>
  {% endif %}

  <div class="dashboard">
    <div class="metric"><span>Contacts</span><strong>{{ stats.total }}</strong></div>
    <div class="metric"><span>Ready</span><strong>{{ stats.ready }}</strong></div>
    <div class="metric"><span>Sent</span><strong>{{ stats.sent }}</strong></div>
    <div class="metric"><span>Replies</span><strong>{{ stats.replies }}</strong></div>
  </div>

  <div class="filters">
    {% for key, label in filter_options %}
    <a href="{{ url_for('index', filter=key) }}" class="{% if current_filter == key %}active{% endif %}">{{ label }}</a>
    {% endfor %}
  </div>

  <form id="crm-form" method="post" action="{{ url_for('save') }}">
    <div class="actions">
      <button type="submit">Save changes</button>
      <button type="button" class="btn" onclick="openDefaultMessageModal()">Default Message</button>
      <button formaction="{{ url_for('send_ready') }}" formmethod="post" type="submit" onclick="return confirm('Send all Ready contacts? Emails go out one at a time.')">Send Ready Emails</button>
      <button type="button" class="btn" onclick="document.getElementById('harvest-modal').classList.add('open')">Reconfigure Contact Harvest</button>
      <button formaction="{{ url_for('find_more') }}" formmethod="post" type="submit" onclick="return confirm('Run harvest and append new contacts? This may take several minutes.')">Find More Contacts</button>
      <a class="btn" href="{{ url_for('test_email') }}">Send Test Email</a>
    </div>
    <table>
      <thead>
        <tr>
          <th>Ready</th>
          <th>Email name</th>
          <th>Status</th>
          <th>Sent</th>
          <th>Jurisdiction</th>
          <th>State</th>
          <th>Contact</th>
          <th>Title</th>
          <th>Email</th>
          <th>Reply</th>
          <th>Notes</th>
          <th>Message</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {% for row in rows %}
        {% set idx = loop.index0 %}
        <tr class="{% if loop.index0 is odd %}row-alt{% endif %}">
          <td>
            <input type="hidden" id="orig-email-{{ idx }}" name="_orig_email" value="{{ row._orig_email }}">
            <input type="hidden" id="orig-state-{{ idx }}" name="_orig_state" value="{{ row._orig_state }}">
            <input type="hidden" id="orig-jurisdiction-{{ idx }}" name="_orig_jurisdiction_name" value="{{ row._orig_jurisdiction_name }}">
            <input type="checkbox" name="approved_{{ idx }}" value="yes"
              {% if row.approved == 'yes' %}checked{% endif %}
              {% if row.send_status == 'sent' %}disabled{% endif %}>
          </td>
          <td><input type="text" name="greeting_name_{{ idx }}" value="{{ row.greeting_name }}"></td>
          <td class="{% if row.send_status == 'sent' %}status-sent{% elif row.send_status == 'failed' %}status-failed{% endif %}">{{ row.send_status or 'prepared' }}</td>
          <td>{{ row.sent_at_display }}</td>
          <td><input type="text" name="jurisdiction_name_{{ idx }}" value="{{ row.jurisdiction_name }}"></td>
          <td><input type="text" name="state_{{ idx }}" value="{{ row.state }}" maxlength="2" style="max-width:40px"></td>
          <td><input type="text" name="contact_name_{{ idx }}" value="{{ row.contact_name }}"></td>
          <td><input type="text" name="contact_title_{{ idx }}" value="{{ row.contact_title }}"></td>
          <td><input type="text" name="email_{{ idx }}" value="{{ row.email }}"></td>
          <td>
            <select name="reply_status_{{ idx }}">
              {% for val in reply_status_values %}
              <option value="{{ val }}" {% if (row.reply_status or 'not_sent') == val %}selected{% endif %}>{{ val }}</option>
              {% endfor %}
            </select>
          </td>
          <td><textarea name="outreach_notes_{{ idx }}" rows="2">{{ row.outreach_notes }}</textarea></td>
          <td>
            <input type="hidden" id="row-subject-{{ idx }}" value="{{ row.message_subject }}">
            <textarea hidden id="row-body-{{ idx }}">{{ row.message_body }}</textarea>
            <button type="button" class="link-btn" onclick="openRowMessageModal({{ idx }})">Email Message</button>
          </td>
          <td>
            <div class="row-menu" id="row-menu-{{ idx }}">
              <button type="button" class="menu-trigger" onclick="toggleRowMenu({{ idx }}, event)" aria-label="Row actions">&#8942;</button>
              <div class="menu-dropdown">
                <button type="button" onclick="openDetailsModal({{ idx }})">Details</button>
                <button type="button" class="menu-delete" onclick="confirmDeleteRow({{ idx }})">Delete</button>
              </div>
            </div>
            <form id="delete-form-{{ idx }}" method="post" action="{{ url_for('delete_row') }}" style="display:none">
              <input type="hidden" name="orig_email" value="{{ row._orig_email }}">
              <input type="hidden" name="orig_state" value="{{ row._orig_state }}">
              <input type="hidden" name="orig_jurisdiction_name" value="{{ row._orig_jurisdiction_name }}">
            </form>
          </td>
          <input type="hidden" id="jurisdiction_type-{{ idx }}" name="jurisdiction_type_{{ idx }}" value="{{ row.jurisdiction_type }}">
          <input type="hidden" id="population-{{ idx }}" name="population_{{ idx }}" value="{{ row.population }}">
          <input type="hidden" id="jurisdiction_url-{{ idx }}" name="jurisdiction_url_{{ idx }}" value="{{ row.jurisdiction_url }}">
          <input type="hidden" id="email_source_url-{{ idx }}" name="email_source_url_{{ idx }}" value="{{ row.email_source_url }}">
          <input type="hidden" id="first_reply_at-{{ idx }}" name="first_reply_at_{{ idx }}" value="{{ row.first_reply_at }}">
          <input type="hidden" id="meeting_scheduled_for-{{ idx }}" name="meeting_scheduled_for_{{ idx }}" value="{{ row.meeting_scheduled_for }}">
          <input type="checkbox" hidden id="meeting_requested-{{ idx }}" name="meeting_requested_{{ idx }}" value="yes" {% if row.meeting_requested == 'yes' %}checked{% endif %}>
          <input type="checkbox" hidden id="meeting_completed-{{ idx }}" name="meeting_completed_{{ idx }}" value="yes" {% if row.meeting_completed == 'yes' %}checked{% endif %}>
          <input type="checkbox" hidden id="follow_up_needed-{{ idx }}" name="follow_up_needed_{{ idx }}" value="yes" {% if row.follow_up_needed == 'yes' %}checked{% endif %}>
          <input type="hidden" id="follow_up_at-{{ idx }}" name="follow_up_at_{{ idx }}" value="{{ row.follow_up_at }}">
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </form>

  <div id="default-message-modal" class="modal-backdrop" onclick="if(event.target===this)this.classList.remove('open')">
    <div class="modal" onclick="event.stopPropagation()">
      <h2>Default Message</h2>
      <form method="post" action="{{ url_for('save_default_message') }}">
        <label>Subject</label>
        <input type="text" name="subject" value="{{ default_message.subject }}">
        <label>Body (use {greeting_name} for personalization)</label>
        <textarea class="body-field" name="body">{{ default_message.body }}</textarea>
        <div class="actions">
          <button type="button" onclick="document.getElementById('default-message-modal').classList.remove('open')">Cancel</button>
          <button type="submit">Save</button>
        </div>
      </form>
    </div>
  </div>

  <div id="row-message-modal" class="modal-backdrop" onclick="if(event.target===this)this.classList.remove('open')">
    <div class="modal" onclick="event.stopPropagation()">
      <h2>Email Message</h2>
      <form method="post" action="{{ url_for('save_row_message') }}">
        <input type="hidden" id="row-msg-orig-email" name="orig_email" value="">
        <input type="hidden" id="row-msg-orig-state" name="orig_state" value="">
        <input type="hidden" id="row-msg-orig-jurisdiction" name="orig_jurisdiction_name" value="">
        <label>Subject</label>
        <input type="text" id="row-msg-subject" name="subject" value="">
        <label>Body (use {greeting_name} for personalization)</label>
        <textarea class="body-field" id="row-msg-body" name="body"></textarea>
        <div class="actions">
          <button type="button" onclick="document.getElementById('row-message-modal').classList.remove('open')">Cancel</button>
          <button type="submit">Save</button>
        </div>
      </form>
    </div>
  </div>

  <div id="details-modal" class="modal-backdrop" onclick="if(event.target===this)this.classList.remove('open')">
    <div class="modal" onclick="event.stopPropagation()">
      <h2>Contact Details</h2>
      <input type="hidden" id="detail-row-idx" value="">
      <label>Jurisdiction type</label>
      <input type="text" id="detail-jurisdiction_type">
      <label>Population</label>
      <input type="text" id="detail-population">
      <label>Jurisdiction URL</label>
      <input type="text" id="detail-jurisdiction_url">
      <label>Email source URL</label>
      <input type="text" id="detail-email_source_url">
      <label>First reply at</label>
      <input type="text" id="detail-first_reply_at">
      <label>Meeting requested</label>
      <input type="checkbox" id="detail-meeting_requested" value="yes">
      <label>Meeting scheduled for</label>
      <input type="text" id="detail-meeting_scheduled_for">
      <label>Meeting completed</label>
      <input type="checkbox" id="detail-meeting_completed" value="yes">
      <label>Follow-up needed</label>
      <input type="checkbox" id="detail-follow_up_needed" value="yes">
      <label>Follow-up date</label>
      <input type="text" id="detail-follow_up_at">
      <div class="actions">
        <button type="button" onclick="document.getElementById('details-modal').classList.remove('open')">Cancel</button>
        <button type="button" onclick="saveDetailsToRow()">Apply to row</button>
      </div>
      <p style="font-size:12px;color:#666">Click Apply, then Save changes on the main form to persist.</p>
    </div>
  </div>

  <div id="harvest-modal" class="modal-backdrop" onclick="if(event.target===this)this.classList.remove('open')">
    <div class="modal" onclick="event.stopPropagation()">
      <h2>Reconfigure Contact Harvest</h2>
      <form method="post" action="{{ url_for('save_harvest_config') }}">
        <label>States (Ctrl+click for multiple)</label>
        <select name="states" multiple>
          {% for st in us_states %}
          <option value="{{ st }}" {% if st in harvest_config.states %}selected{% endif %}>{{ st }}</option>
          {% endfor %}
        </select>
        <div class="row">
          <div>
            <label>Min population</label>
            <input type="text" name="min_population" value="{{ harvest_config.min_population }}">
          </div>
          <div>
            <label>Max population</label>
            <input type="text" name="max_population" value="{{ harvest_config.max_population }}">
          </div>
        </div>
        <label>Limit</label>
        <input type="text" name="limit" value="{{ harvest_config.limit }}">
        <label><input type="checkbox" name="include_counties" value="yes" {% if harvest_config.include_counties %}checked{% endif %}> Include counties</label>
        <label><input type="checkbox" name="deep_mode" value="yes" {% if harvest_config.deep_mode %}checked{% endif %}> Deep mode</label>
        <div class="actions">
          <button type="button" onclick="document.getElementById('harvest-modal').classList.remove('open')">Cancel</button>
          <button type="submit">Save Settings</button>
          <button formaction="{{ url_for('run_harvest') }}" formmethod="post" type="submit" onclick="return confirm('Save settings and run full harvest? This may take several minutes.')">Run Harvest</button>
        </div>
      </form>
    </div>
  </div>
</body>
</html>
"""

TEST_PAGE_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Send Test Email</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 16px; max-width: 820px; }
    .msg { padding: 8px; background: #eef6ff; border: 1px solid #99c; margin-bottom: 12px; }
    .panel { border: 1px solid #ccc; padding: 12px; margin: 12px 0; background: #fafafa; }
    label { display: block; font-weight: bold; margin-top: 8px; }
    input[type=text] { width: 100%; max-width: 320px; padding: 6px; box-sizing: border-box; }
    pre { white-space: pre-wrap; background: #fff; border: 1px solid #ddd; padding: 12px; }
    .actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
    button, a.btn { padding: 8px 12px; cursor: pointer; text-decoration: none; color: #111; border: 1px solid #888; background: #fafafa; }
    .history { font-size: 13px; color: #444; }
  </style>
</head>
<body>
  <h1>Send Test Email</h1>
  <p>Test the full outreach template and Gmail pipeline without modifying prospect records.</p>
  <p><a class="btn" href="{{ url_for('index') }}">&larr; Back to outreach review</a></p>
  {% if message %}<div class="msg">{{ message }}</div>{% endif %}

  <form method="get" action="{{ url_for('test_email') }}">
    <div class="panel">
      <p><strong>To:</strong> {{ to_email }}</p>
      <p><strong>Contact name (reference only):</strong> {{ contact_name }}</p>
      <label for="greeting_name">Greeting name</label>
      <input id="greeting_name" type="text" name="greeting_name" value="{{ greeting_name }}">
      <div class="actions">
        <button type="submit">Update preview</button>
      </div>
    </div>
  </form>

  <div class="panel">
    <p><strong>Subject:</strong> {{ subject }}</p>
    <label>Preview</label>
    <pre>{{ body_preview }}</pre>
  </div>

  <form method="post">
    <input type="hidden" name="greeting_name" value="{{ greeting_name }}">
    <div class="actions">
      <button formaction="{{ url_for('test_create_draft') }}" formmethod="post" type="submit">Create Test Draft</button>
      <button formaction="{{ url_for('test_send') }}" formmethod="post" type="submit">Send Test Email</button>
    </div>
  </form>

  <div class="panel history">
    <h3>Last test activity</h3>
    <p><strong>Last test draft:</strong> {{ history.get('last_test_draft_at') or '—' }}</p>
    <p><strong>Last test send:</strong> {{ history.get('last_test_send_at') or '—' }}</p>
    <p><strong>Last test greeting:</strong> {{ history.get('last_test_greeting') or '—' }}</p>
  </div>
</body>
</html>
"""


def _row_count() -> int:
    return len(request.form.getlist("_orig_email"))


def _parse_form_updates() -> list[dict[str, str]]:
    count = _row_count()
    updates: list[dict[str, str]] = []
    for idx in range(count):
        updates.append(
            {
                "_orig_email": request.form.getlist("_orig_email")[idx],
                "_orig_state": request.form.getlist("_orig_state")[idx],
                "_orig_jurisdiction_name": request.form.getlist("_orig_jurisdiction_name")[idx],
                "approved": "yes" if request.form.get(f"approved_{idx}") == "yes" else "",
                "greeting_name": request.form.get(f"greeting_name_{idx}", ""),
                "jurisdiction_type": request.form.get(f"jurisdiction_type_{idx}", ""),
                "population": request.form.get(f"population_{idx}", ""),
                "jurisdiction_name": request.form.get(f"jurisdiction_name_{idx}", ""),
                "state": request.form.get(f"state_{idx}", ""),
                "contact_name": request.form.get(f"contact_name_{idx}", ""),
                "contact_title": request.form.get(f"contact_title_{idx}", ""),
                "email": request.form.get(f"email_{idx}", ""),
                "jurisdiction_url": request.form.get(f"jurisdiction_url_{idx}", ""),
                "email_source_url": request.form.get(f"email_source_url_{idx}", ""),
                "reply_status": request.form.get(f"reply_status_{idx}", "not_sent"),
                "first_reply_at": request.form.get(f"first_reply_at_{idx}", ""),
                "meeting_requested": "yes"
                if request.form.get(f"meeting_requested_{idx}") == "yes"
                else "",
                "meeting_scheduled_for": request.form.get(f"meeting_scheduled_for_{idx}", ""),
                "meeting_completed": "yes"
                if request.form.get(f"meeting_completed_{idx}") == "yes"
                else "",
                "follow_up_needed": "yes"
                if request.form.get(f"follow_up_needed_{idx}") == "yes"
                else "",
                "follow_up_at": request.form.get(f"follow_up_at_{idx}", ""),
                "outreach_notes": request.form.get(f"outreach_notes_{idx}", ""),
            }
        )
    return updates


def _display_rows(all_rows: list[dict[str, str]], filter_name: str) -> list[dict[str, str]]:
    rows = []
    for row in all_rows:
        if not row_matches_filter(row, filter_name):
            continue
        display = dict(row)
        display["_orig_email"] = row.get("email", "")
        display["_orig_state"] = row.get("state", "")
        display["_orig_jurisdiction_name"] = row.get("jurisdiction_name", "")
        display["sent_at_display"] = format_sent_date_display(row.get("sent_at", ""))
        subject, body = row_message_templates(row)
        display["message_subject"] = subject
        display["message_body"] = body
        rows.append(display)
    return rows


def _parse_harvest_form() -> HarvestConfigSettings:
    states = [s.strip().upper() for s in request.form.getlist("states") if s.strip()]
    if not states:
        states = load_harvest_config().states
    return HarvestConfigSettings(
        states=states,
        min_population=int(request.form.get("min_population", 20000)),
        max_population=int(request.form.get("max_population", 100000)),
        limit=int(request.form.get("limit", 50)),
        include_counties=request.form.get("include_counties") == "yes",
        deep_mode=request.form.get("deep_mode") == "yes",
    )


def create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index():
        filter_name = request.args.get("filter", "all")
        all_rows = read_outreach_rows()
        stats = compute_dashboard(all_rows)
        rows = _display_rows(all_rows, filter_name)
        message = request.args.get("msg", "")
        if request.args.get("harvest") == "1":
            from src.harvest_summary import load_harvest_summary

            summary = load_harvest_summary()
            if summary:
                message = summary.format_message()
        harvest_config = load_harvest_config()
        default_message = load_default_message()
        return render_template_string(
            PAGE_TEMPLATE,
            rows=rows,
            stats=stats,
            filter_options=FILTER_OPTIONS,
            current_filter=filter_name,
            reply_status_values=REPLY_STATUS_VALUES,
            harvest_config=harvest_config,
            default_message=default_message,
            us_states=US_STATE_CODES,
            message=message,
        )

    @app.post("/save")
    def save():
        updates = _parse_form_updates()
        update_outreach_rows(updates)
        filter_name = request.args.get("filter", "all")
        return redirect(url_for("index", filter=filter_name, msg="Saved changes."))

    @app.post("/row/delete")
    def delete_row():
        ok = delete_outreach_row(
            request.form.get("orig_email", ""),
            request.form.get("orig_state", ""),
            request.form.get("orig_jurisdiction_name", ""),
        )
        filter_name = request.args.get("filter", "all")
        msg = "Contact removed." if ok else "Contact not found."
        return redirect(url_for("index", filter=filter_name, msg=msg))

    @app.post("/harvest-config/save")
    def save_harvest_config():
        settings = _parse_harvest_form()
        persist_harvest_config(settings)
        return redirect(url_for("index", msg="Harvest settings saved."))

    @app.post("/harvest-config/run")
    def run_harvest():
        settings = _parse_harvest_form()
        persist_harvest_config(settings)
        try:
            run_find_more_contacts()
            return redirect(url_for("index", harvest="1"))
        except Exception as exc:
            msg = f"Harvest failed: {exc}"
        return redirect(url_for("index", msg=msg))

    @app.post("/find-more")
    def find_more():
        updates = _parse_form_updates()
        if updates:
            update_outreach_rows(updates)
        try:
            run_find_more_contacts()
            return redirect(url_for("index", harvest="1"))
        except Exception as exc:
            msg = f"Find more contacts failed: {exc}"
        return redirect(url_for("index", msg=msg))

    @app.post("/default-message/save")
    def save_default_message():
        subject = request.form.get("subject", "")
        body = request.form.get("body", "")
        save_default_message_for_outreach(subject, body)
        return redirect(url_for("index", msg="Default message saved."))

    @app.post("/row-message/save")
    def save_row_message():
        ok = persist_row_message(
            request.form.get("orig_email", ""),
            request.form.get("orig_state", ""),
            request.form.get("orig_jurisdiction_name", ""),
            request.form.get("subject", ""),
            request.form.get("body", ""),
        )
        msg = "Row message saved." if ok else "Row not found."
        return redirect(url_for("index", msg=msg))

    @app.post("/send-ready")
    def send_ready():
        updates = _parse_form_updates()
        if updates:
            update_outreach_rows(updates)
        args = argparse.Namespace(delay_seconds=2.0)
        try:
            service = build_gmail_service()
            verify_gmail_account(service)
            code = run_outreach_send_ready(args, service=service)
        except Exception as exc:
            return redirect(url_for("index", msg=f"Send error: {exc}"))
        msg = "Ready emails sent." if code == 0 else "Send failed."
        return redirect(url_for("index", msg=msg))

    @app.get("/test")
    def test_email():
        greeting = request.args.get("greeting_name", DEFAULT_TEST_GREETING)
        content = render_test_outreach(greeting)
        history = load_test_history()
        message = request.args.get("msg", "")
        return render_template_string(
            TEST_PAGE_TEMPLATE,
            to_email=TEST_RECIPIENT_EMAIL,
            contact_name=TEST_RECIPIENT_NAME,
            greeting_name=content["greeting_name"],
            subject=content["subject"],
            body_preview=content["body"],
            history=history,
            message=message,
        )

    @app.post("/test/draft")
    def test_create_draft():
        greeting = request.form.get("greeting_name", DEFAULT_TEST_GREETING)
        try:
            service = build_gmail_service()
            verify_gmail_account(service)
            _, draft_id = create_test_draft(service, greeting)
            msg = f"Test Gmail draft created (id={draft_id})."
        except Exception as exc:
            msg = f"Test draft failed: {exc}"
        return redirect(url_for("test_email", greeting_name=greeting, msg=msg))

    @app.post("/test/send")
    def test_send():
        greeting = request.form.get("greeting_name", DEFAULT_TEST_GREETING)
        try:
            service = build_gmail_service()
            verify_gmail_account(service)
            content, draft_id, message_id = send_test_email(service, greeting)
            msg = (
                f"Test email sent to {content['to_email']} "
                f"(draft id={draft_id}, message id={message_id})."
            )
        except Exception as exc:
            msg = f"Test send failed: {exc}"
        return redirect(url_for("test_email", greeting_name=greeting, msg=msg))

    return app


def run_outreach_server(
    host: str = "127.0.0.1",
    port: int = OUTREACH_PORT,
    *,
    open_browser: bool = False,
) -> None:
    if port != OUTREACH_PORT:
        raise ValueError(f"Contacts CRM must use port {OUTREACH_PORT}, not {port}")
    check_port_available(host, port)
    app = create_app()
    print(f"Outreach CRM UI: {CRM_URL}")
    print(f"Test email:      {CRM_URL}/test")
    if open_browser:
        schedule_browser_open()
    app.run(host=host, port=port, debug=False)
